#!/usr/bin/env python3
"""Exercise actual direct-TLS Vaultwarden Compose with disposable storage.

Run on the Docker host: python3 tests/vaultwarden_e2e.py
Needs Python's standard library, Docker Compose, openssl and the installed vault
image. Never reads .env, creates vault accounts, installs browser/system trust,
or mounts real vault data. Each run owns a fresh exodus-vault-e2e-* project and
private temporary host data/TLS directories. Health is not proof of device sync.
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
import ssl
import struct
import subprocess
import tempfile
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("vaultwarden",)
# Public, test-only PHC example from Vaultwarden's admin-token documentation.
# Never copied to the live deployment or used to log in.
TEST_ADMIN_HASH = (
    "$argon2id$v=19$m=19456,t=2,p=1$"
    "cXpKdUxHSWhlaUs1QVVsSStkbTRPQVFPSmdpamFCMHdvYjVkWTVKaDdpYz0$"
    "E1UgBKjUCD2Roy0jdHAJvXihugpG+N9WcAaR8P6Qn/8"
)


class IsolatedVault:
    def __init__(self, *, compatibility_overlay=False):
        self.project = "exodus-vault-e2e-" + uuid.uuid4().hex[:12]
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.directory = tempfile.TemporaryDirectory(prefix=self.project + "-")
        self.path = Path(self.directory.name).resolve()
        self.data_dir = self.path / "data"
        self.tls_dir = self.path / "tls"
        self.data_dir.mkdir(mode=0o700)
        self.tls_dir.mkdir(mode=0o700)
        self.env = {
            key: value for key, value in os.environ.items()
            if key in {"PATH", "HOME", "TMPDIR", "XDG_CONFIG_HOME", "SYSTEMROOT"}
            or key.startswith("DOCKER_")
        }
        self.env.update(
            VAULTWARDEN_PORT=str(self.port),
            VAULTWARDEN_DOMAIN=f"https://127.0.0.1:{self.port}",
            VAULTWARDEN_DATA_DIR=str(self.data_dir),
            VAULTWARDEN_TLS_DIR=str(self.tls_dir),
            VAULTWARDEN_SIGNUPS_ALLOWED="true",
            COMPOSE_ANSI="never",
        )
        self.compose = [
            "docker", "compose", "--env-file", os.devnull,
            "--project-name", self.project,
            "--file", str(ROOT / "docker-compose.yml"),
        ]
        if compatibility_overlay:
            self.compose += ["--file", str(ROOT / "docker-compose.vaultwarden-tls.yml")]
        # Exercise the unchanged production probe more often in disposable runs.
        timing = self.path / 'health-timing.json'
        timing.write_text(json.dumps({'services': {'vaultwarden': {'healthcheck': {'interval': '1s', 'start_period': '1s'}}}}))
        self.compose += ['--file', str(timing)]
        self.created_volumes = []
        self.compose_started = False
        self.closed = False
        self.config = {}

    def run(self, args, *, input_text=None, timeout=120, check=True):
        result = subprocess.run(args, cwd=ROOT, env=self.env, input=input_text,
                                text=True, capture_output=True, timeout=timeout)
        if check and result.returncode:
            # Only disposable input is used. Never print config/inspect stdout
            # or stdin containing even the public test admin hash.
            raise RuntimeError(f"Disposable operation failed ({result.returncode}): " + result.stderr[-1200:])
        return result.stdout.strip()

    def certificates(self):
        ca_config = self.tls_dir / "ca.cnf"
        ca_config.write_text(
            "[req]\nprompt = no\ndistinguished_name = dn\nx509_extensions = ca\n"
            "[dn]\nCN = Exodus disposable TLS test CA\n"
            "[ca]\nbasicConstraints = critical,CA:TRUE\nkeyUsage = critical,keyCertSign,cRLSign\n"
        )
        leaf_config = self.tls_dir / "leaf.cnf"
        leaf_config.write_text(
            "basicConstraints = critical,CA:FALSE\nkeyUsage = critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage = serverAuth\nsubjectAltName = DNS:localhost,DNS:vaultwarden,IP:127.0.0.1\n"
        )
        self.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                  "-sha256", "-keyout", str(self.tls_dir / "ca-key.pem"),
                  "-out", str(self.tls_dir / "ca.pem"), "-config", str(ca_config)])
        self.run(["openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes",
                  "-keyout", str(self.tls_dir / "key.pem"), "-out", str(self.tls_dir / "request.csr"),
                  "-subj", "/CN=localhost"])
        self.run(["openssl", "x509", "-req", "-in", str(self.tls_dir / "request.csr"),
                  "-CA", str(self.tls_dir / "ca.pem"), "-CAkey", str(self.tls_dir / "ca-key.pem"),
                  "-CAcreateserial", "-days", "1", "-sha256", "-extfile", str(leaf_config),
                  "-out", str(self.tls_dir / "leaf.pem")])
        # A chain file lets both Rocket and the existing curl --cacert health
        # command use the same configured certificate file with verification.
        (self.tls_dir / "cert.pem").write_bytes((self.tls_dir / "leaf.pem").read_bytes() + (self.tls_dir / "ca.pem").read_bytes())
        for name in ("cert.pem", "key.pem"):
            (self.tls_dir / name).chmod(0o644)
        (self.tls_dir / "ca-key.pem").chmod(0o600)
        self.context = ssl.create_default_context(cafile=str(self.tls_dir / "ca.pem"))

    def start(self):
        self.certificates()
        self.config = json.loads(self.run(self.compose + ["config", "--format", "json"]))
        if "vaultwarden-gateway" in self.config["services"]:
            raise AssertionError("Direct-TLS Compose must not create a gateway")
        vault = self.config["services"]["vaultwarden"]
        if vault.get("container_name"):
            raise AssertionError("Refusing a fixed container name")
        for mount in vault.get("volumes", []):
            if mount["type"] == "volume":
                logical = mount["source"]
                volume = self.config["volumes"][logical]
                name = volume["name"]
                if volume.get("external") or not name.startswith(self.project + "_"):
                    raise AssertionError("Refusing a non-test Docker volume")
                self.run(["docker", "volume", "create", "--label", "com.docker.compose.project=" + self.project,
                          "--label", "com.docker.compose.volume=" + logical, name])
                self.created_volumes.append(name)
            elif mount["type"] == "bind":
                source = Path(mount["source"]).resolve()
                data = source == self.data_dir and mount["target"] == "/data" and not mount.get("read_only")
                tls = source in {self.tls_dir / "cert.pem", self.tls_dir / "key.pem"} and mount.get("read_only")
                if not (data or tls) or not source.exists():
                    raise AssertionError("Refusing a bind outside disposable data/TLS paths")
            else:
                raise AssertionError("Unexpected mount type")
        for logical in vault.get("networks", {}):
            network = self.config["networks"][logical]
            if network.get("external") or not network["name"].startswith(self.project + "_"):
                raise AssertionError("Refusing a non-test network")
        mounts = {m["target"]: m for m in vault["volumes"]}
        secret_name = self.config["volumes"][mounts["/run/secrets"]["source"]]["name"]
        self.run([
            "docker", "run", "--rm", "--pull", "never", "-i", "--network", "none", "--user", "0:0", "--entrypoint", "sh",
            "--mount", f"type=bind,source={self.data_dir},target=/test-data",
            "--mount", f"type=volume,source={secret_name},target=/run/secrets", vault["image"], "-ec",
            "umask 077; cat > /run/secrets/vaultwarden_admin_token; "
            "chown -R 1000:1000 /test-data /run/secrets; chmod 700 /test-data /run/secrets; "
            "chmod 600 /run/secrets/vaultwarden_admin_token",
        ], input_text=TEST_ADMIN_HASH + "\n")
        self.compose_started = True
        self.run(self.compose + ["up", "--detach", "--no-deps", "--pull", "never", "vaultwarden"])
        self.wait_healthy()

    def container(self, service="vaultwarden"):
        identity = self.run(self.compose + ["ps", "--all", "--quiet", service])
        if not identity or "\n" in identity:
            raise AssertionError("Expected one disposable vault container")
        return json.loads(self.run(["docker", "inspect", identity]))[0]

    def wait_healthy(self, timeout=90):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.container()["State"]
            if state.get("Health", {}).get("Status") == "healthy":
                try:
                    if self.request("/alive")[0] == 200:
                        return
                except (OSError, http.client.HTTPException):
                    pass
            if state.get("Status") in {"dead", "exited"}:
                raise AssertionError("Disposable Vaultwarden exited during startup")
            time.sleep(1)
        raise AssertionError("Disposable Vaultwarden did not pass verified TLS health within 90 seconds")

    def request(self, path, *, method="GET", body=None, headers=None):
        connection = http.client.HTTPSConnection("127.0.0.1", self.port, context=self.context, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read(2 * 1024 * 1024)
        finally:
            connection.close()

    def recreate(self):
        self.run(self.compose + ["up", "--detach", "--no-deps", "--pull", "never", "--force-recreate", "vaultwarden"])
        self.wait_healthy()

    def close(self):
        if self.closed:
            return
        failures = []
        if not self.project.startswith("exodus-vault-e2e-"):
            raise AssertionError("Refusing to remove a non-test project")
        if self.compose_started:
            try:
                self.run(self.compose + ["down", "--volumes", "--remove-orphans", "--timeout", "5"])
            except Exception as exc:
                failures.append(str(exc))
        for name in self.created_volumes:
            self.run(["docker", "volume", "rm", name], check=False)
        if self.config and self.data_dir.exists():
            try:
                # Restore host access only to the disposable folder for cleanup.
                self.run(["docker", "run", "--rm", "--pull", "never", "--network", "none", "--user", "0:0", "--entrypoint", "sh",
                          "--mount", f"type=bind,source={self.data_dir},target=/test-data",
                          self.config["services"]["vaultwarden"]["image"], "-ec", "chmod -R a+rwX /test-data"])
            except Exception as exc:
                failures.append(str(exc))
        for resource, args in (("containers", ["docker", "ps", "--all", "--quiet"]),
                               ("volumes", ["docker", "volume", "ls", "--quiet"]),
                               ("networks", ["docker", "network", "ls", "--quiet"])):
            if self.run(args + ["--filter", "label=com.docker.compose.project=" + self.project]):
                failures.append("Disposable " + resource + " remain for " + self.project)
        self.directory.cleanup()
        self.closed = True
        if failures:
            raise RuntimeError("; ".join(failures))


def masked_frame(opcode, payload):
    if len(payload) >= 126:
        raise AssertionError("Only short test WebSocket frames are needed")
    mask = os.urandom(4)
    return bytes([0x80 | opcode, 0x80 | len(payload)]) + mask + bytes(value ^ mask[index % 4] for index, value in enumerate(payload))


def read_exact(stream, count):
    data = stream.read(count)
    if len(data) != count:
        raise AssertionError("WebSocket ended before its frame was complete")
    return data


def assert_websocket(test, vault):
    key = base64.b64encode(os.urandom(16)).decode()
    path = "/notifications/anonymous-hub?token=" + uuid.uuid4().hex
    with socket.create_connection(("127.0.0.1", vault.port), timeout=5) as raw:
        with vault.context.wrap_socket(raw, server_hostname="localhost") as connection:
            connection.sendall((f"GET {path} HTTP/1.1\r\nHost: localhost:{vault.port}\r\n"
                                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                                f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
            with connection.makefile("rb") as stream:
                test.assertIn(b" 101 ", stream.readline(4096))
                headers = {}
                for _ in range(100):
                    line = stream.readline(8192)
                    if line == b"\r\n": break
                    test.assertTrue(line, "WebSocket headers ended unexpectedly")
                    name, value = line.decode().split(":", 1); headers[name.lower()] = value.strip()
                expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
                test.assertEqual(headers["sec-websocket-accept"], expected)
                connection.sendall(masked_frame(1, b'{"protocol":"messagepack","version":1}\x1e'))
                for _ in range(5):
                    first, second = read_exact(stream, 2)
                    length = second & 0x7F
                    if length == 126: length = struct.unpack("!H", read_exact(stream, 2))[0]
                    elif length == 127: length = struct.unpack("!Q", read_exact(stream, 8))[0]
                    test.assertLess(length, 65536)
                    test.assertFalse(second & 0x80)
                    payload = read_exact(stream, length)
                    opcode = first & 0x0F
                    if opcode == 9:
                        connection.sendall(masked_frame(10, payload)); continue
                    test.assertIn(opcode, (1, 2)); test.assertEqual(payload, b"{}\x1e"); break
                else: test.fail("No native SignalR protocol response")
                connection.sendall(masked_frame(8, struct.pack("!H", 1000)))
    test.assertEqual(vault.request("/notifications/hub", headers={"Connection": "Upgrade", "Upgrade": "websocket",
                    "Sec-WebSocket-Key": key, "Sec-WebSocket-Version": "13"})[0], 401)


class VaultwardenEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vault = IsolatedVault()
        cls.addClassCleanup(cls.vault.close)
        print(f"\nStarting disposable direct-TLS project {cls.vault.project}", flush=True)
        cls.vault.start()

    def test_container_hardening_and_loopback_port(self):
        vault = self.vault.container()
        self.assertEqual(vault["Config"]["User"], "1000:1000")
        self.assertTrue(vault["HostConfig"]["ReadonlyRootfs"])
        self.assertIn("ALL", vault["HostConfig"]["CapDrop"])
        self.assertFalse(vault["HostConfig"].get("CapAdd"))
        self.assertTrue(any("no-new-privileges" in flag for flag in vault["HostConfig"]["SecurityOpt"]))
        self.assertIn("/tmp", vault["HostConfig"]["Tmpfs"])
        self.assertEqual(vault["HostConfig"]["Sysctls"]["net.ipv4.ip_unprivileged_port_start"], "0")
        self.assertEqual(vault["NetworkSettings"]["Ports"]["80/tcp"], [{"HostIp": "127.0.0.1", "HostPort": str(self.vault.port)}])
        mounts = {m["Destination"]: m for m in vault["Mounts"]}
        self.assertTrue(mounts["/data"]["RW"])
        self.assertEqual(mounts["/data"]["Type"], "bind")
        for path in ("/run/secrets", "/run/tls/cert.pem", "/run/tls/key.pem"):
            self.assertFalse(mounts[path]["RW"])
        self.assertNotIn("/var/run/docker.sock", mounts)
        self.assertFalse(any(value.startswith("ADMIN_TOKEN=") for value in vault["Config"]["Env"]))

    def test_root_health_config_and_authenticated_api(self):
        status, _, body = self.vault.request("/alive")
        self.assertEqual(status, 200); self.assertIsInstance(json.loads(body), str)
        status, _, body = self.vault.request("/api/config")
        self.assertEqual(status, 200)
        config = json.loads(body)
        self.assertEqual(config["environment"]["vault"].rstrip('/'), f"https://127.0.0.1:{self.vault.port}")
        self.assertEqual(self.vault.request("/api/sync")[0], 401)
        self.assertNotEqual(self.vault.request("/vault/alive")[0], 200, "Old subpath must not be required")

    def test_web_vault_assets_and_native_framing_protection(self):
        status, headers, body = self.vault.request("/")
        headers = {key.lower(): value for key, value in headers.items()}
        self.assertEqual(status, 200); self.assertIn("text/html", headers["content-type"])
        self.assertIn(b"<app-root>", body)
        script = re.search(rb'<script[^>]+src="([^\"]+\.js)"', body)
        style = re.search(rb'<link[^>]+href="([^\"]+\.css)"', body)
        self.assertIsNotNone(script); self.assertIsNotNone(style)
        for asset in (script.group(1), style.group(1)):
            asset = asset.decode(); self.assertFalse(asset.startswith(("http:", "https:", "//")))
            self.assertEqual(self.vault.request("/" + asset.lstrip("/"))[0], 200)
        self.assertEqual(headers["x-frame-options"], "SAMEORIGIN")
        self.assertIn("frame-ancestors 'self'", headers["content-security-policy"])
        self.assertNotIn("frame-ancestors *", headers["content-security-policy"])
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        # Native Rocket headers are preserved. No gateway-added HSTS or Host
        # filter is claimed by this integration.

    def test_notifications_upgrade_over_verified_tls(self):
        assert_websocket(self, self.vault)

    def test_registration_policy_toggle_without_creating_account(self):
        path = "/identity/accounts/register/send-verification-email"
        body = json.dumps({"email": uuid.uuid4().hex + "@example.invalid", "name": "Disposable policy check"})
        headers = {"Content-Type": "application/json"}
        status, _, response = self.vault.request(path, method="POST", body=body, headers=headers)
        self.assertEqual(status, 200, "Onboarding preflight should be accepted without SMTP; no password/key is submitted")
        self.assertNotIn(b"Registration not allowed", response)
        try:
            self.vault.env["VAULTWARDEN_SIGNUPS_ALLOWED"] = "false"
            self.vault.recreate()
            status, _, response = self.vault.request(path, method="POST", body=body, headers=headers)
            self.assertEqual(status, 400); self.assertIn(b"Registration not allowed", response)
        finally:
            self.vault.env["VAULTWARDEN_SIGNUPS_ALLOWED"] = "true"
            self.vault.recreate()

    def test_persistence_across_recreation(self):
        before = self.vault.container()["Id"]
        marker = uuid.uuid4().hex
        self.vault.run(["docker", "exec", "-i", before, "sh", "-ec", "cat > /data/.exodus-e2e-marker; test -s /data/db.sqlite3"], input_text=marker)
        key_hash = self.vault.run(["docker", "exec", before, "sha256sum", "/data/rsa_key.pem"])
        self.vault.recreate()
        after = self.vault.container()["Id"]
        self.assertNotEqual(before, after)
        self.assertEqual(self.vault.run(["docker", "exec", after, "cat", "/data/.exodus-e2e-marker"]), marker)
        self.assertEqual(self.vault.run(["docker", "exec", after, "sha256sum", "/data/rsa_key.pem"]), key_hash)

    def test_offline_failure_and_recovery(self):
        try:
            self.vault.run(self.vault.compose + ["stop", "--timeout", "5", "vaultwarden"])
            with self.assertRaises((OSError, http.client.HTTPException)):
                self.vault.request("/alive")
        finally:
            self.vault.run(self.vault.compose + ["up", "--detach", "--no-deps", "--pull", "never", "vaultwarden"])
            self.vault.wait_healthy()
        self.assertEqual(self.vault.request("/alive")[0], 200)

    def test_startup_rejects_missing_empty_and_unreadable_admin_secret(self):
        definition = self.vault.config["services"]["vaultwarden"]
        entrypoint = definition["entrypoint"]
        with tempfile.TemporaryDirectory(prefix="exodus-vault-guard-") as temporary:
            secret = Path(temporary) / "admin-token"
            for state in ("missing", "empty", "unreadable"):
                with self.subTest(secret=state):
                    name = self.vault.project + "-guard-" + state
                    command = ["docker", "run", "--rm", "--pull", "never", "--name", name,
                               "--network", "none", "--read-only", "--user", definition["user"],
                               "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                               "--env", "ADMIN_TOKEN_FILE=/run/secrets/vaultwarden_admin_token", "--entrypoint", entrypoint[0]]
                    if state != "missing":
                        secret.write_text("" if state == "empty" else "disposable-test-token\n")
                        secret.chmod(0o644 if state == "empty" else 0o000)
                        command += ["--mount", "type=bind,source=" + str(secret) + ",target=/run/secrets/vaultwarden_admin_token,readonly"]
                    command += [definition["image"], *entrypoint[1:]]
                    try:
                        result = subprocess.run(command, cwd=ROOT, env=self.vault.env, text=True, capture_output=True, timeout=15)
                        self.assertEqual(result.returncode, 1)
                        self.assertIn("admin secret is missing or unreadable", result.stderr)
                        self.assertNotIn("Starting Vaultwarden", result.stdout)
                        self.assertNotIn("disposable-test-token", result.stdout + result.stderr)
                    finally:
                        self.vault.run(["docker", "rm", "--force", name], check=False)
                        if secret.exists(): secret.chmod(0o600)


if __name__ == "__main__":
    try:
        result = unittest.main(verbosity=2, exit=False).result
    finally:
        instance = getattr(VaultwardenEndToEnd, "vault", None)
        if instance: instance.close()
    raise SystemExit(0 if result.wasSuccessful() else 1)
