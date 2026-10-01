#!/usr/bin/env python3
"""Exercise the real Vaultwarden + gateway Compose services with disposable data.

Run on the Docker host: python3 tests/vaultwarden_e2e.py

Only Python's standard library and Docker Compose are needed. The test deliberately
does not load .env or docker-compose.override.yml, create accounts, send mail, or
mount the real vault. Every resource has a fresh exodus-vault-e2e-* project name.
The test does NOT prove account synchronization, browser rendering, or remote TLS.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import tempfile
import time
import unittest
from urllib.parse import urlsplit
import uuid


ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("vaultwarden", "vaultwarden-gateway")
# Public, test-only PHC example from Vaultwarden's admin-token documentation.
# Never copied to the actual deployment, and never used to log in.
TEST_ADMIN_HASH = (
    "$argon2id$v=19$m=19456,t=2,p=1$"
    "cXpKdUxHSWhlaUs1QVVsSStkbTRPQVFPSmdpamFCMHdvYjVkWTVKaDdpYz0$"
    "E1UgBKjUCD2Roy0jdHAJvXihugpG+N9WcAaR8P6Qn/8"
)


class IsolatedVault:
    def __init__(self):
        self.project = "exodus-vault-e2e-" + uuid.uuid4().hex[:12]
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        # Preserve Docker's connection/runtime settings, but never application
        # credentials or Compose project/volume/domain overrides from the shell.
        self.env = {
            key: value for key, value in os.environ.items()
            if key in {"PATH", "HOME", "TMPDIR", "XDG_CONFIG_HOME", "SYSTEMROOT"}
            or key.startswith("DOCKER_")
        }
        self.env.update(
            VAULTWARDEN_PORT=str(self.port),
            VAULTWARDEN_DOMAIN=f"http://localhost:{self.port}/vault",
            COMPOSE_ANSI="never",
        )
        self.compose = [
            "docker", "compose", "--env-file", os.devnull,
            "--project-name", self.project,
            "--file", str(ROOT / "docker-compose.yml"),
        ]
        self.created_volumes: list[str] = []
        self.compose_started = False
        self.closed = False
        self.config: dict = {}

    def run(self, args, *, input_text=None, timeout=120, check=True):
        result = subprocess.run(
            args, cwd=ROOT, env=self.env, input=input_text,
            text=True, capture_output=True, timeout=timeout,
        )
        if check and result.returncode:
            # Never print inspect/config stdout: it may contain secret settings.
            raise RuntimeError(
                f"Docker operation failed ({result.returncode}): "
                + result.stderr[-1600:]
            )
        return result.stdout.strip()

    def start(self):
        self.config = json.loads(self.run(self.compose + ["config", "--format", "json"]))
        for service in SERVICES:
            definition = self.config["services"][service]
            if definition.get("container_name"):
                raise AssertionError("E2E services must not use fixed container names")
            for mount in definition.get("volumes", []):
                if mount["type"] == "volume":
                    logical = mount["source"]
                    volume = self.config["volumes"][logical]
                    name = volume["name"]
                    if volume.get("external") or not name.startswith(self.project + "_"):
                        raise AssertionError("Refusing to use a non-test Docker volume")
                    if name not in self.created_volumes:
                        self.run([
                            "docker", "volume", "create",
                            "--label", "com.docker.compose.project=" + self.project,
                            "--label", "com.docker.compose.volume=" + logical, name,
                        ])
                        self.created_volumes.append(name)
                elif mount["type"] == "bind":
                    source = Path(mount["source"]).resolve()
                    safe_config = ROOT / "config" / "vaultwarden"
                    if (not mount.get("read_only") or not source.is_file()
                            or not source.is_relative_to(safe_config)):
                        raise AssertionError("Refusing to mount writable or private host data")
                else:
                    raise AssertionError("Unexpected Compose mount type")
            for logical in definition.get("networks", {}):
                network = self.config["networks"][logical]
                if network.get("external") or not network["name"].startswith(self.project + "_"):
                    raise AssertionError("Refusing to use a non-test Docker network")

        vault = self.config["services"]["vaultwarden"]
        data_mount = next(m for m in vault["volumes"] if m["target"] == "/data/vaultwarden")
        secret_mount = next(m for m in vault["volumes"] if m["target"] == "/run/secrets")
        data_name = self.config["volumes"][data_mount["source"]]["name"]
        secret_name = self.config["volumes"][secret_mount["source"]]["name"]
        # Only the disposable volumes receive this public test token/ownership.
        self.run([
            "docker", "run", "--rm", "-i", "--network", "none", "--user", "0:0",
            "--entrypoint", "sh",
            "--mount", f"type=volume,source={data_name},target=/data/vaultwarden",
            "--mount", f"type=volume,source={secret_name},target=/run/secrets",
            vault["image"], "-ec",
            "umask 077; cat > /run/secrets/vaultwarden_admin_token; "
            "chown -R 1000:1000 /data/vaultwarden /run/secrets; "
            "chmod 700 /data/vaultwarden /run/secrets; "
            "chmod 600 /run/secrets/vaultwarden_admin_token",
        ], input_text=TEST_ADMIN_HASH + "\n")
        self.compose_started = True
        self.run(self.compose + ["up", "--detach", "--no-deps", *SERVICES])
        self.wait_healthy()

    def container(self, service):
        container_id = self.run(self.compose + ["ps", "--all", "--quiet", service])
        if not container_id or "\n" in container_id:
            raise AssertionError(f"Expected one disposable {service} container")
        return json.loads(self.run(["docker", "inspect", container_id]))[0]

    def wait_healthy(self, timeout=90):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            states = [self.container(service)["State"] for service in SERVICES]
            if all(s.get("Health", {}).get("Status") == "healthy" for s in states):
                try:
                    if self.request("/vault/alive")[0] == 200:
                        return
                except (OSError, http.client.HTTPException):
                    pass  # Gateway can briefly reconnect during recreation.
            if any(s.get("Status") in {"dead", "exited"} for s in states):
                raise AssertionError("Disposable vault or gateway exited during startup")
            time.sleep(1)
        raise AssertionError("Disposable vault/gateway did not become healthy within 90 seconds")

    def request(self, path, *, method="GET", body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read(2 * 1024 * 1024)
        finally:
            connection.close()

    def close(self):
        if self.closed:
            return
        failures = []
        if self.compose_started:
            try:
                self.run(self.compose + ["down", "--volumes", "--remove-orphans", "--timeout", "5"])
            except Exception as exc:
                failures.append(str(exc))
        for name in self.created_volumes:
            # A Compose failure may leave a seeded volume behind. Names are
            # checked before creation, and no global prune operation is used.
            try:
                self.run(["docker", "volume", "rm", name], check=False)
            except Exception as exc:
                failures.append(str(exc))
        remaining = self.run([
            "docker", "ps", "--all", "--quiet", "--filter",
            "label=com.docker.compose.project=" + self.project,
        ])
        remaining_volumes = self.run([
            "docker", "volume", "ls", "--quiet", "--filter",
            "label=com.docker.compose.project=" + self.project,
        ])
        remaining_networks = self.run([
            "docker", "network", "ls", "--quiet", "--filter",
            "label=com.docker.compose.project=" + self.project,
        ])
        if remaining or remaining_volumes or remaining_networks:
            failures.append("Disposable test resources remain for project " + self.project)
        if failures:
            raise RuntimeError("; ".join(failures))
        self.closed = True


def masked_frame(opcode, payload):
    if len(payload) >= 126:
        raise AssertionError("Only short test WebSocket frames are needed")
    mask = os.urandom(4)
    return bytes([0x80 | opcode, 0x80 | len(payload)]) + mask + bytes(
        value ^ mask[index % 4] for index, value in enumerate(payload)
    )


def read_exact(stream, count):
    data = stream.read(count)
    if len(data) != count:
        raise AssertionError("WebSocket ended before its frame was complete")
    return data


class VaultwardenEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vault = IsolatedVault()
        cls.addClassCleanup(cls.vault.close)
        print(f"\nStarting disposable project {cls.vault.project}", flush=True)
        cls.vault.start()

    def test_startup_rejects_missing_empty_and_unreadable_admin_secret(self):
        definition = self.vault.config["services"]["vaultwarden"]
        entrypoint = definition["entrypoint"]
        self.assertIsInstance(entrypoint, list)
        with tempfile.TemporaryDirectory(prefix="exodus-vault-guard-") as temporary:
            secret = Path(temporary) / "admin-token"
            for state in ("missing", "empty", "unreadable"):
                with self.subTest(secret=state):
                    name = self.vault.project + "-guard-" + state
                    command = [
                        "docker", "run", "--rm", "--name", name,
                        "--network", "none", "--read-only", "--user", definition["user"],
                        "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                        "--env", "ADMIN_TOKEN_FILE=/run/secrets/vaultwarden_admin_token",
                        "--entrypoint", entrypoint[0],
                    ]
                    if state != "missing":
                        secret.write_text("" if state == "empty" else "disposable-test-token\n")
                        secret.chmod(0o644 if state == "empty" else 0o000)
                        command += ["--mount", "type=bind,source=" + str(secret)
                                    + ",target=/run/secrets/vaultwarden_admin_token,readonly"]
                    command += [definition["image"], *entrypoint[1:]]
                    try:
                        result = subprocess.run(command, cwd=ROOT, env=self.vault.env,
                                                text=True, capture_output=True, timeout=15)
                        self.assertEqual(result.returncode, 1)
                        self.assertIn("admin secret is missing or unreadable", result.stderr)
                        self.assertNotIn("Starting Vaultwarden", result.stdout)
                        self.assertNotIn("disposable-test-token", result.stdout + result.stderr)
                    finally:
                        self.vault.run(["docker", "rm", "--force", name], check=False)
                        if secret.exists():
                            secret.chmod(0o600)

    def test_container_hardening_and_port_isolation(self):
        vault = self.vault.container("vaultwarden")
        gateway = self.vault.container("vaultwarden-gateway")
        self.assertEqual(vault["Config"]["User"], "1000:1000")
        self.assertTrue(vault["HostConfig"]["ReadonlyRootfs"])
        self.assertIn("ALL", vault["HostConfig"]["CapDrop"])
        self.assertTrue(any("no-new-privileges" in flag for flag in vault["HostConfig"]["SecurityOpt"]))
        self.assertIn("/tmp", vault["HostConfig"]["Tmpfs"])
        self.assertFalse(any(vault["NetworkSettings"]["Ports"].values()))
        published = [binding for values in gateway["NetworkSettings"]["Ports"].values() for binding in values or []]
        self.assertEqual(published, [{"HostIp": "127.0.0.1", "HostPort": str(self.vault.port)}])
        self.assertEqual(gateway["Config"]["User"], "1000:1000")
        self.assertTrue(gateway["HostConfig"]["ReadonlyRootfs"])
        self.assertIn("ALL", gateway["HostConfig"]["CapDrop"])
        # The official Caddy binary's file capability requires this one
        # capability even when it listens on an unprivileged port.
        self.assertEqual([cap.removeprefix("CAP_") for cap in gateway["HostConfig"]["CapAdd"]], ["NET_BIND_SERVICE"])
        networks = vault["NetworkSettings"]["Networks"]
        self.assertEqual(set(networks), {self.vault.project + "_vault_private"})
        network = json.loads(self.vault.run(["docker", "network", "inspect", next(iter(networks))]))[0]
        self.assertTrue(network["Internal"])
        mounts = {m["Destination"]: m for m in vault["Mounts"]}
        self.assertFalse(mounts["/run/secrets"]["RW"])
        self.assertTrue(mounts["/data/vaultwarden"]["RW"])
        self.assertNotIn("/var/run/docker.sock", mounts)
        self.assertFalse(any(value.startswith("ADMIN_TOKEN=") for value in vault["Config"]["Env"]))

    def test_gateway_redirect_health_and_closed_registration(self):
        status, headers, _ = self.vault.request("/vault")
        self.assertIn(status, (301, 302, 307, 308))
        self.assertEqual(urlsplit(headers.get("Location", "")).path, "/vault/")
        status, _, body = self.vault.request("/vault/alive")
        self.assertEqual(status, 200)
        self.assertIsInstance(json.loads(body), str)
        status, _, body = self.vault.request("/vault/api/config")
        self.assertEqual(status, 200)
        config = json.loads(body)
        self.assertIsInstance(config["settings"]["disableUserRegistration"], bool)
        self.assertEqual(config["environment"]["vault"], f"http://localhost:{self.vault.port}/vault")
        self.assertEqual(self.vault.request("/vault/api/sync")[0], 401)
        # That UI flag also depends on invitations/SMTP. Invited onboarding
        # can keep it false even when anonymous signup is correctly disabled.
        # Exercise the actual policy with a brand-new, uninvited test address.
        status, _, body = self.vault.request(
            "/vault/identity/accounts/register", method="POST",
            headers={"Content-Type": "application/json"},
            body=json.dumps({
                "email": uuid.uuid4().hex + "@example.invalid",
                "masterPasswordHash": "disposable-test-hash",
                "key": "disposable-test-key", "kdf": 0, "kdfIterations": 600000,
            }),
        )
        self.assertEqual(status, 400)
        self.assertTrue(b"Registration not allowed" in body,
                        "Expected an explicit registration-disabled rejection")

    def test_web_vault_and_framing_protection(self):
        status, headers, body = self.vault.request("/vault/")
        self.assertEqual(status, 200)
        headers = {key.lower(): value for key, value in headers.items()}
        self.assertIn("text/html", headers["content-type"])
        # Recent web-vault builds use relative assets instead of <base href>.
        # Fetch actual script/style references to detect broken subpath proxying.
        script = re.search(rb'<script[^>]+src="([^\"]+\.js)"', body)
        style = re.search(rb'<link[^>]+href="([^\"]+\.css)"', body)
        self.assertIsNotNone(script, "Web vault script is missing")
        self.assertIsNotNone(style, "Web vault stylesheet is missing")
        for asset in (script.group(1), style.group(1)):
            asset_path = asset.decode()
            self.assertFalse(asset_path.startswith(("/", "http:" , "https:")))
            self.assertEqual(self.vault.request("/vault/" + asset_path)[0], 200)
        self.assertEqual(headers["x-frame-options"], "SAMEORIGIN")
        self.assertIn("frame-ancestors 'self'", headers["content-security-policy"])
        self.assertNotIn("frame-ancestors *", headers["content-security-policy"])
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        self.assertEqual(self.vault.request("/vault/", headers={"Host": "untrusted.invalid"})[0], 421)
        # The separate vault origin deliberately cannot be framed by Exodus.
        # HTTP loopback is not TLS; no false HSTS/HTTPS assertion is made here.

    def test_websocket_proxy_upgrade_and_protocol_response(self):
        key = base64.b64encode(os.urandom(16)).decode()
        path = "/vault/notifications/anonymous-hub?token=" + uuid.uuid4().hex
        with socket.create_connection(("127.0.0.1", self.vault.port), timeout=5) as connection:
            connection.sendall((
                f"GET {path} HTTP/1.1\r\nHost: localhost:{self.vault.port}\r\n"
                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
            ).encode())
            stream = connection.makefile("rb")
            self.assertIn(b" 101 ", stream.readline(4096))
            headers = {}
            while True:
                line = stream.readline(8192)
                if line == b"\r\n":
                    break
                self.assertTrue(line, "WebSocket headers ended unexpectedly")
                name, value = line.decode().split(":", 1)
                headers[name.lower()] = value.strip()
            expected = base64.b64encode(hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
            ).digest()).decode()
            self.assertEqual(headers["sec-websocket-accept"], expected)
            connection.sendall(masked_frame(1, b'{"protocol":"messagepack","version":1}\x1e'))
            for _ in range(5):
                first, second = read_exact(stream, 2)
                length = second & 0x7F
                if length == 126:
                    length = struct.unpack("!H", read_exact(stream, 2))[0]
                elif length == 127:
                    length = struct.unpack("!Q", read_exact(stream, 8))[0]
                self.assertLess(length, 65536)
                self.assertFalse(second & 0x80, "Server WebSocket frames must not be masked")
                payload = read_exact(stream, length)
                opcode = first & 0x0F
                if opcode == 9:
                    connection.sendall(masked_frame(10, payload))
                    continue
                self.assertIn(opcode, (1, 2))
                self.assertEqual(payload, b"{}\x1e")
                break
            else:
                self.fail("No SignalR protocol response received through gateway")
            connection.sendall(masked_frame(8, struct.pack("!H", 1000)))
            stream.close()

        # Protected notifications must continue enforcing their own auth.
        status, _, _ = self.vault.request("/vault/notifications/hub", headers={
            "Connection": "Upgrade", "Upgrade": "websocket",
            "Sec-WebSocket-Key": key, "Sec-WebSocket-Version": "13",
        })
        self.assertEqual(status, 401)

    def test_persistence_across_container_recreation(self):
        before = self.vault.container("vaultwarden")["Id"]
        marker = uuid.uuid4().hex
        self.vault.run(["docker", "exec", "-i", before, "sh", "-ec",
                        "cat > /data/vaultwarden/.exodus-e2e-marker; test -s /data/vaultwarden/db.sqlite3"],
                       input_text=marker)
        key_hash = self.vault.run(["docker", "exec", before, "sha256sum", "/data/vaultwarden/rsa_key.pem"])
        self.vault.run(self.vault.compose + ["up", "--detach", "--no-deps", "--force-recreate", "vaultwarden"])
        self.vault.wait_healthy()
        after = self.vault.container("vaultwarden")["Id"]
        self.assertNotEqual(before, after)
        self.assertEqual(self.vault.run(["docker", "exec", after, "cat", "/data/vaultwarden/.exodus-e2e-marker"]), marker)
        self.assertEqual(self.vault.run(["docker", "exec", after, "sha256sum", "/data/vaultwarden/rsa_key.pem"]), key_hash)

    def test_offline_failure_and_recovery(self):
        try:
            self.vault.run(self.vault.compose + ["stop", "--timeout", "5", "vaultwarden"])
            self.assertIn(self.vault.request("/vault/alive")[0], (502, 503))
        finally:
            self.vault.run(self.vault.compose + ["up", "--detach", "--no-deps", "vaultwarden"])
            self.vault.wait_healthy()
        self.assertEqual(self.vault.request("/vault/alive")[0], 200)


if __name__ == "__main__":
    try:
        result = unittest.main(verbosity=2, exit=False).result
    finally:
        # Also clean up when interrupted during setUpClass or a Docker call.
        instance = getattr(VaultwardenEndToEnd, "vault", None)
        if instance:
            instance.close()
    raise SystemExit(0 if result.wasSuccessful() else 1)
