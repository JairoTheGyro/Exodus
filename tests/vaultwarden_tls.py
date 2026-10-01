#!/usr/bin/env python3
"""Test the optional local HTTPS overlay with a disposable CA and real services.

Run on the Docker host: python3 tests/vaultwarden_tls.py

Requires Docker Compose and openssl. Uses only the Python standard library. The
test never reads .env, mounts the real vault, installs CA trust, disables TLS
validation, or changes the user's active services. The generated test CA is
trusted only by this test's explicit SSL context, then removed with its keys.
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
import tempfile
import unittest

from vaultwarden_e2e import IsolatedVault, ROOT, SERVICES, TEST_ADMIN_HASH


class IsolatedTLSVault(IsolatedVault):
    def __init__(self):
        super().__init__()
        self.directory = tempfile.TemporaryDirectory(prefix="exodus-vault-tls-")
        self.tls_dir = Path(self.directory.name).resolve()
        self.env.update(
            VAULTWARDEN_TLS_DIR=str(self.tls_dir),
            VAULTWARDEN_DOMAIN=f"https://localhost:{self.port}/vault",
        )
        self.compose += ["--file", str(ROOT / "docker-compose.vaultwarden-tls.yml")]

    def certificates(self):
        ca_config = self.tls_dir / "ca.cnf"
        ca_config.write_text(
            "[req]\nprompt = no\ndistinguished_name = dn\nx509_extensions = ca\n"
            "[dn]\nCN = Exodus disposable TLS test CA\n"
            "[ca]\nbasicConstraints = critical,CA:TRUE\nkeyUsage = critical,keyCertSign,cRLSign\n",
            encoding="utf-8",
        )
        leaf_config = self.tls_dir / "leaf.cnf"
        leaf_config.write_text(
            "basicConstraints = critical,CA:FALSE\n"
            "keyUsage = critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage = serverAuth\nsubjectAltName = DNS:localhost\n",
            encoding="utf-8",
        )
        self.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-sha256", "-keyout", str(self.tls_dir / "ca-key.pem"),
            "-out", str(self.tls_dir / "ca.pem"), "-config", str(ca_config),
        ])
        self.run([
            "openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(self.tls_dir / "key.pem"), "-out", str(self.tls_dir / "request.csr"),
            "-subj", "/CN=localhost",
        ])
        self.run([
            "openssl", "x509", "-req", "-in", str(self.tls_dir / "request.csr"),
            "-CA", str(self.tls_dir / "ca.pem"), "-CAkey", str(self.tls_dir / "ca-key.pem"),
            "-CAcreateserial", "-days", "1", "-sha256", "-extfile", str(leaf_config),
            "-out", str(self.tls_dir / "cert.pem"),
        ])
        # The containing host directory is mode 0700; Docker binds only these
        # two files, and its unprivileged uid1000 can read their mounted paths.
        os.chmod(self.tls_dir, 0o700)
        for name in ("cert.pem", "key.pem"):
            os.chmod(self.tls_dir / name, 0o644)
        os.chmod(self.tls_dir / "ca-key.pem", 0o600)
        self.context = ssl.create_default_context(cafile=str(self.tls_dir / "ca.pem"))

    def start(self):
        self.certificates()
        self.config = json.loads(self.run(self.compose + ["config", "--format", "json"]))
        for name in SERVICES:
            service = self.config["services"][name]
            if service.get("container_name"):
                raise AssertionError("Refusing a fixed container name in isolated TLS test")
            for mount in service.get("volumes", []):
                if mount["type"] == "volume":
                    logical = mount["source"]
                    definition = self.config["volumes"][logical]
                    volume = definition["name"]
                    if definition.get("external") or not volume.startswith(self.project + "_"):
                        raise AssertionError("Refusing a non-test volume")
                    if volume not in self.created_volumes:
                        self.run([
                            "docker", "volume", "create", "--label", "com.docker.compose.project=" + self.project,
                            "--label", "com.docker.compose.volume=" + logical, volume,
                        ])
                        self.created_volumes.append(volume)
                elif mount["type"] == "bind":
                    source = Path(mount["source"]).resolve()
                    allowed = source.is_relative_to(ROOT / "config" / "vaultwarden") or source in {
                        self.tls_dir / "cert.pem", self.tls_dir / "key.pem",
                    }
                    if not mount.get("read_only") or not source.is_file() or not allowed:
                        raise AssertionError("Refusing a private or writable host mount")
                else:
                    raise AssertionError("Unexpected mount type")
            for logical in service.get("networks", {}):
                definition = self.config["networks"][logical]
                if definition.get("external") or not definition["name"].startswith(self.project + "_"):
                    raise AssertionError("Refusing a non-test network")

        vault = self.config["services"]["vaultwarden"]
        mounts = {mount["target"]: mount for mount in vault["volumes"]}
        data = self.config["volumes"][mounts["/data/vaultwarden"]["source"]]["name"]
        secret = self.config["volumes"][mounts["/run/secrets"]["source"]]["name"]
        self.run([
            "docker", "run", "--rm", "-i", "--network", "none", "--user", "0:0", "--entrypoint", "sh",
            "--mount", f"type=volume,source={data},target=/data/vaultwarden",
            "--mount", f"type=volume,source={secret},target=/run/secrets", vault["image"], "-ec",
            "umask 077; cat > /run/secrets/vaultwarden_admin_token; "
            "chown -R 1000:1000 /data/vaultwarden /run/secrets; "
            "chmod 700 /data/vaultwarden /run/secrets; chmod 600 /run/secrets/vaultwarden_admin_token",
        ], input_text=TEST_ADMIN_HASH + "\n")
        self.compose_started = True
        self.run(self.compose + ["up", "--detach", "--no-deps", *SERVICES])
        self.wait_healthy()

    def request(self, path, *, method="GET", body=None, headers=None):
        connection = http.client.HTTPSConnection("localhost", self.port, context=self.context, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read(2 * 1024 * 1024)
        finally:
            connection.close()

    def close(self):
        try:
            super().close()
        finally:
            self.directory.cleanup()


class VaultwardenTLSChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vault = IsolatedTLSVault()
        cls.addClassCleanup(cls.vault.close)
        print(f"\nStarting disposable TLS project {cls.vault.project}", flush=True)
        cls.vault.start()

    def test_valid_ca_and_hostname_are_required(self):
        self.assertTrue(self.vault.context.check_hostname)
        self.assertEqual(self.vault.context.verify_mode, ssl.CERT_REQUIRED)
        self.assertEqual(self.vault.request("/vault/alive")[0], 200)
        for host, context in (("localhost", ssl.create_default_context()), ("127.0.0.1", self.vault.context)):
            connection = http.client.HTTPSConnection(host, self.vault.port, context=context, timeout=5)
            try:
                with self.assertRaises(ssl.SSLCertVerificationError):
                    connection.request("GET", "/vault/alive")
                    connection.getresponse()
            finally:
                connection.close()

    def test_https_headers_native_csp_and_registration_policy(self):
        status, headers, body = self.vault.request("/vault/")
        headers = {key.lower(): value for key, value in headers.items()}
        self.assertEqual(status, 200)
        self.assertTrue(b"<app-root>" in body, "Expected the native web-vault application shell")
        script = re.search(rb'<script[^>]+src="([^"/][^"]+)"', body)
        self.assertIsNotNone(script, "Expected a relative web-vault JavaScript asset")
        self.assertEqual(self.vault.request("/vault/" + script.group(1).decode())[0], 200)
        self.assertEqual(headers["strict-transport-security"], "max-age=0")
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        self.assertEqual(headers["x-frame-options"], "SAMEORIGIN")
        self.assertIn("frame-ancestors 'self'", headers["content-security-policy"])
        self.assertNotIn("frame-ancestors *", headers["content-security-policy"])
        status, _, body = self.vault.request("/vault/api/config")
        self.assertEqual(status, 200)
        config = json.loads(body)
        self.assertEqual(config["environment"]["vault"], f"https://localhost:{self.vault.port}/vault")
        # The UI keeps registration visible for invited people when SMTP is
        # disabled. Verify actual signup enforcement, not that presentation flag.
        # Official 1.37.3 src/config.rs:is_signup_disabled and identity.rs govern
        # this distinction. This uninvited address cannot create an account.
        status, _, body = self.vault.request(
            "/vault/identity/accounts/register/send-verification-email", method="POST",
            body=json.dumps({"email": "uninvited@example.invalid", "name": "Disposable TLS check"}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 400)
        self.assertTrue(b"Registration not allowed" in body, "Expected closed-registration refusal")
        self.assertEqual(self.vault.request("/vault/api/sync")[0], 401)
        self.assertEqual(self.vault.request("/vault/", headers={"Host": "untrusted.invalid"})[0], 421)

    def test_loopback_binding_and_private_health_only_listener(self):
        gateway = self.vault.container("vaultwarden-gateway")
        published = [binding for values in gateway["NetworkSettings"]["Ports"].values() for binding in values or []]
        self.assertEqual(published, [{"HostIp": "127.0.0.1", "HostPort": str(self.vault.port)}])
        self.assertFalse(gateway["NetworkSettings"]["Ports"].get("8081/tcp"))
        mounts = {mount["Destination"]: mount for mount in gateway["Mounts"]}
        for path in ("/run/tls/cert.pem", "/run/tls/key.pem"):
            self.assertFalse(mounts[path]["RW"])
        self.assertEqual(gateway["Config"]["User"], "1000:1000")
        internal = self.vault.run([
            "docker", "exec", gateway["Id"], "sh", "-c",
            "wget -S -O /dev/null http://127.0.0.1:8081/vault/alive 2>&1",
        ])
        self.assertIn("200 OK", internal)
        self.assertNotIn("strict-transport-security", internal.lower())
        for path in ("/vault/", "/vault/admin", "/vault/api/config"):
            internal = self.vault.run([
                "docker", "exec", gateway["Id"], "sh", "-c",
                f"wget -S -O /dev/null http://127.0.0.1:8081{path} 2>&1",
            ], check=False)
            self.assertIn("404 Not Found", internal)
        connection = http.client.HTTPConnection("127.0.0.1", self.vault.port, timeout=5)
        try:
            connection.request("GET", "/vault/")
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            self.assertNotIn("strict-transport-security", {key.lower() for key, _ in response.getheaders()})
        finally:
            connection.close()

    def test_notifications_can_upgrade_over_verified_tls(self):
        key = base64.b64encode(os.urandom(16)).decode()
        with socket.create_connection(("127.0.0.1", self.vault.port), timeout=5) as raw:
            with self.vault.context.wrap_socket(raw, server_hostname="localhost") as connection:
                connection.sendall((
                    "GET /vault/notifications/anonymous-hub?token=disposable-tls-test HTTP/1.1\r\n"
                    f"Host: localhost:{self.vault.port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                    f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
                ).encode())
                with connection.makefile("rb") as stream:
                    self.assertIn(b" 101 ", stream.readline(4096))
                    headers = {}
                    for _ in range(100):
                        line = stream.readline(8192)
                        if line == b"\r\n":
                            break
                        self.assertTrue(line)
                        name, value = line.decode().split(":", 1)
                        headers[name.lower()] = value.strip()
                    expected = base64.b64encode(hashlib.sha1(
                        (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
                    ).digest()).decode()
                    self.assertEqual(headers["sec-websocket-accept"], expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
