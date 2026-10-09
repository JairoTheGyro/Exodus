"""Isolated Vaultwarden companion routes; no real vault or credentials touched.

Run: docker exec -i sovereign-hub-odysseus-1 python - < tests/vaultwarden_integration.py
Container launch checks are covered separately by the deployment smoke suite.
This suite also verifies actual disposable loopback TLS handshakes.
"""
import asyncio
import os
import json
import ssl
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

_temp = tempfile.TemporaryDirectory(prefix="exodus-vaultwarden-tests-")
os.environ["ODYSSEUS_DATA_DIR"] = _temp.name
os.environ["DATABASE_URL"] = "sqlite:///" + _temp.name + "/test.db"
os.environ["AUTH_ENABLED"] = "true"
os.environ["LOCALHOST_BYPASS"] = "false"

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.vaultwarden_routes import setup_vaultwarden_routes
from src import vaultwarden_service
from src.ai_policy import WorkspacePolicyMiddleware, allowed_without_ai
from src.home_store import database, save
from src.vaultwarden_service import VaultwardenService


class VaultwardenChecks(unittest.TestCase):
    def setUp(self):
        self.settings = patch.dict(os.environ, {
            "VAULTWARDEN_INTERNAL_URL": "https://vaultwarden:80/alive",
            "VAULTWARDEN_PUBLIC_URL": "https://localhost:8092/",
            "VAULTWARDEN_CA_FILE": "",
            "VAULTWARDEN_SIGNUPS_ALLOWED": "true",
            "VAULTWARDEN_ADMIN_TOKEN": "synthetic-secret-never-exposed",
        })
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.requests = []
        self.response = httpx.Response(200, json="2026-10-01T14:12:00.000000Z")
        self.failure = None

        def transport(request):
            self.requests.append(request)
            if self.failure:
                raise self.failure
            return self.response

        self.service = VaultwardenService(httpx.MockTransport(transport))
        app = FastAPI()
        app.state.auth_manager = SimpleNamespace(is_configured=True)
        app.add_middleware(WorkspacePolicyMiddleware)

        @app.middleware("http")
        async def identity(request, call_next):
            request.state.current_user = request.headers.get("x-test-user")
            request.state.api_token = request.headers.get("x-test-token") == "yes"
            request.state.api_token_owner = request.headers.get("x-test-owner")
            return await call_next(request)

        app.include_router(setup_vaultwarden_routes(self.service))
        self.client = TestClient(app, follow_redirects=False)
        self.client.headers["x-test-user"] = "alice"
        with database() as db:
            db.execute("DELETE FROM profiles")

    def test_routes_work_in_both_account_modes_without_exposing_vault_data(self):
        for mode in ("full", "ai-free"):
            with database() as db:
                save("alice", {"mode": mode}, db)
            config = self.client.get("/api/vaultwarden/config")
            self.assertEqual(config.status_code, 200, config.text)
            self.assertEqual(config.json(), {
                "vault_url": "https://localhost:8092/", "launch_path": "/vault",
                "access_mode": "https", "registration_allowed": True,
                "registration_policy_source": "deployment", "embedded": False,
                "start_command": "docker compose -p sovereign-hub up -d --no-deps vaultwarden",
                "admin_enabled": True,
            })
            status = self.client.get("/api/vaultwarden/status")
            self.assertEqual(status.status_code, 200, status.text)
            self.assertEqual(status.json()["status"], "running")
            self.assertEqual(status.json()["sync"]["status"], "unknown")
            self.assertIn("cannot verify", status.json()["sync"]["detail"])
            self.assertIn("checked_at", status.json())
            for path in ("/vault", "/vault/"):
                redirect = self.client.get(path)
                self.assertEqual(redirect.status_code, 303)
                self.assertEqual(redirect.headers["location"], config.json()["vault_url"])
            for response in (config, status, redirect):
                self.assertIn("no-store", response.headers["cache-control"])
                self.assertEqual(response.headers["referrer-policy"], "no-referrer")
                self.assertNotIn("set-cookie", response.headers)
                self.assertNotIn("synthetic-secret", response.text)

    def test_mode_allowlist_is_read_only_and_exact(self):
        for path in ("/api/vaultwarden/status", "/api/vaultwarden/config"):
            self.assertTrue(allowed_without_ai(path, "GET"))
            self.assertFalse(allowed_without_ai(path, "POST"))
            self.assertFalse(allowed_without_ai(path + "/anything", "GET"))
        self.assertFalse(allowed_without_ai("/api/vaultwarden/start", "POST"))

    def test_browser_auth_is_required_and_delegated_tokens_are_denied(self):
        paths = ("/api/vaultwarden/status", "/api/vaultwarden/config", "/vault", "/vault/")
        del self.client.headers["x-test-user"]
        for path in paths:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401, response.text)
            self.assertIn("no-store", response.headers["cache-control"])
        self.client.headers.update({"x-test-user": "api", "x-test-token": "yes", "x-test-owner": "admin"})
        for path in paths:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 403)
            self.assertNotIn("location", response.headers)
        self.assertEqual(self.requests, [])

    def test_client_headers_and_untrusted_urls_cannot_reach_health_request(self):
        self.client.headers.update({"Authorization": "Bearer synthetic-browser-secret", "Cookie": "session=synthetic-cookie"})
        response = self.client.get("/api/vaultwarden/status?url=http://169.254.169.254/secret&topic=private")
        self.assertEqual(response.json()["status"], "running")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual({str(request.url) for request in self.requests}, {
            "https://vaultwarden:80/alive",
        })
        for request in self.requests:
            for name in ("authorization", "cookie", "x-test-user", "x-test-owner"):
                self.assertNotIn(name, request.headers)
        self.assertNotIn("synthetic-browser-secret", response.text)

    def test_offline_and_ssl_failures_are_generic_and_do_not_block_routes(self):
        for failure in (
            httpx.ConnectError("password=synthetic-secret-never-exposed"),
            httpx.ConnectError("CERTIFICATE_VERIFY_FAILED: private.internal"),
            httpx.ReadTimeout("synthetic-secret-never-exposed"),
        ):
            self.failure = failure
            response = self.client.get("/api/vaultwarden/status")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "offline")
            self.assertEqual(response.json()["sync"]["status"], "unknown")
            self.assertNotIn("synthetic-secret", response.text)
            self.assertNotIn("private.internal", response.text)
            self.assertEqual(self.client.get("/api/vaultwarden/config").status_code, 200)

    def test_bad_heartbeat_is_degraded_and_redirects_are_not_followed(self):
        for response in (
            httpx.Response(503, text="private server log"),
            httpx.Response(302, headers={"location": "http://169.254.169.254/credentials"}),
            httpx.Response(200, text="<html>A different service</html>"),
            httpx.Response(200, json={"admin_token": "synthetic-secret-never-exposed"}),
            httpx.Response(200, json="not a timestamp"),
            httpx.Response(200, content=b"x" * 4096),
        ):
            self.response = response
            self.requests.clear()
            result = self.client.get("/api/vaultwarden/status")
            self.assertEqual(result.json()["status"], "degraded")
            self.assertEqual(len(self.requests), 1)
            self.assertNotIn("private server log", result.text)
            self.assertNotIn("synthetic-secret", result.text)

    def test_legacy_gateway_setting_is_unused_and_only_one_vault_is_probed(self):
        with patch.dict(os.environ, {'VAULTWARDEN_GATEWAY_HEALTH_URL':'http://169.254.169.254/private'}):
            response = self.client.get('/api/vaultwarden/status')
            self.assertEqual(response.json()['status'], 'running')
            self.assertEqual(response.json()['checks'], {'vault':'running'})
            self.assertEqual(len(self.requests), 1)
            self.assertEqual(str(self.requests[0].url), 'https://vaultwarden:80/alive')
            self.assertNotIn('gateway', response.text)
            self.assertNotIn('gateway', self.client.get('/api/vaultwarden/config').text)

    def test_health_uses_strict_defaults_and_ignores_environment_proxy(self):
        original = httpx.AsyncClient
        with patch.dict(os.environ, {"HTTP_PROXY": "http://proxy.invalid:9000"}):
            with patch("src.vaultwarden_service.httpx.AsyncClient", wraps=original) as client:
                self.assertEqual(self.client.get("/api/vaultwarden/status").json()["status"], "running")
        kwargs = client.call_args.kwargs
        self.assertFalse(kwargs["trust_env"])
        self.assertFalse(kwargs["follow_redirects"])
        self.assertIsInstance(kwargs["verify"], ssl.SSLContext)
        self.assertTrue(kwargs["verify"].check_hostname)
        self.assertEqual(kwargs["verify"].verify_mode, ssl.CERT_REQUIRED)
        self.assertGreater(kwargs["verify"].cert_store_stats()["x509_ca"], 0)
        self.assertEqual(kwargs["timeout"].connect, 3.0)
        self.assertEqual(kwargs["timeout"].read, 3.0)

    def test_overall_deadline_cancels_stalled_http_request(self):
        cancelled = []

        async def slow(request):
            try:
                await asyncio.sleep(20)
            finally:
                cancelled.append(True)

        self.service.transport = httpx.MockTransport(slow)
        self.assertEqual(vaultwarden_service.HEALTH_TIMEOUT_SECONDS, 3.0)
        started = time.monotonic()
        with patch("src.vaultwarden_service.HEALTH_TIMEOUT_SECONDS", 0.04):
            response = self.client.get("/api/vaultwarden/status")
        self.assertEqual(response.json()["status"], "offline")
        self.assertLess(time.monotonic() - started, 0.75)
        self.assertEqual(cancelled, [True])

    def test_defaults_and_registration_flag_describe_deployment_only(self):
        with patch.dict(os.environ):
            for name in ('VAULTWARDEN_INTERNAL_URL','VAULTWARDEN_PUBLIC_URL','VAULTWARDEN_SIGNUPS_ALLOWED'):
                os.environ.pop(name, None)
            self.assertEqual(self.service.connection_urls(), ('https://vaultwarden:80/alive','https://127.0.0.1:8092/'))
            config = self.client.get('/api/vaultwarden/config').json()
            self.assertFalse(config['registration_allowed'])
            self.assertEqual(config['registration_policy_source'], 'deployment')
        for flag, expected in [('true',True),('1',True),('false',False),('0',False)]:
            with patch.dict(os.environ, {'VAULTWARDEN_SIGNUPS_ALLOWED':flag}):
                self.assertEqual(self.client.get('/api/vaultwarden/config').json()['registration_allowed'],expected)
        with patch.dict(os.environ, {'VAULTWARDEN_SIGNUPS_ALLOWED':'synthetic-invalid-setting'}):
            response = self.client.get('/api/vaultwarden/config')
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('synthetic-invalid-setting', response.text)
        self.assertEqual(self.requests, [])

    def test_public_url_requires_loopback_http_or_https_and_root_or_legacy_vault_path(self):
        valid = {
            "https://localhost:8092/": "https",
            "https://localhost:8092": "https",
            "https://vault.example.test/": "https",
            "http://localhost:8092/vault": "local",
            "http://127.0.0.1:8092/vault/": "local",
            "http://[::1]:8092/vault/": "local",
            "https://vault.example.test/vault/": "https",
        }
        for url, access_mode in valid.items():
            with patch.dict(os.environ, {"VAULTWARDEN_PUBLIC_URL": url}):
                response = self.client.get("/api/vaultwarden/config")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["access_mode"], access_mode)
                self.assertEqual(response.json()["vault_url"], url.rstrip("/") + "/")
        invalid = (
            "http://vault.example.test/vault/", "http://localhost.evil.test/vault/",
            "https://user:synthetic-secret@example.test/vault/", "//example.test/vault/",
            "javascript:alert(1)", "https://example.test/admin", "https://example.test/vault/../admin",
            "https://example.test/vault?token=synthetic-secret", "https://example.test/vault/#private",
            "https://example.test/vault/?", "https://example.test/vault/#",
            "https://example.test/%76ault/", "https://example.test/vault\\admin",
            "\nhttps://example.test/vault/", "https://exam\tple.test/vault/",
            "https://example.test:0/vault/", "https://example.test:99999/vault/",
            "https://-bad.test/vault/", "https://example.test /vault/",
        )
        for url in invalid:
            with patch.dict(os.environ, {"VAULTWARDEN_PUBLIC_URL": url}):
                for path in ("/api/vaultwarden/config", "/api/vaultwarden/status", "/vault"):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 503, url)
                    self.assertNotIn("synthetic-secret", response.text)
                    self.assertNotIn("location", response.headers)
                    self.assertIn("no-store", response.headers["cache-control"])
        self.assertEqual(self.requests, [])

    def test_internal_url_cannot_be_retargeted_to_arbitrary_host_or_path(self):
        for url in (
            "https://169.254.169.254/alive", "https://example.test/alive",
            "http://vaultwarden:8080/admin", "http://vaultwarden:8080/vault/alive?token=secret",
            "http://vaultwarden.evil.test/vault/alive", "http://secret@vaultwarden:8080/vault/alive",
        ):
            with patch.dict(os.environ, {"VAULTWARDEN_INTERNAL_URL": url}):
                response = self.client.get("/api/vaultwarden/status")
                self.assertEqual(response.status_code, 503, url)
                self.assertNotIn(url, response.text)
        self.assertEqual(self.requests, [])

    def test_local_ca_file_extends_default_trust_and_invalid_file_is_redacted(self):
        with temporary_tls_server() as (server_url, cert_file, _):
            original = httpx.AsyncClient
            with patch.dict(os.environ, {'VAULTWARDEN_CA_FILE':str(cert_file)}):
                with patch('src.vaultwarden_service.httpx.AsyncClient', wraps=original) as client:
                    self.assertEqual(self.client.get('/api/vaultwarden/status').json()['status'], 'running')
                context = client.call_args.kwargs['verify']
                self.assertTrue(context.check_hostname)
                self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
                pem = cert_file.read_text()
                self.assertIn(ssl.PEM_cert_to_DER_cert(pem), context.get_ca_certs(binary_form=True))
                self.assertGreater(len(context.get_ca_certs()), 1, 'Default trust remains available')
        for cafile in (str(Path(_temp.name)/'synthetic-private-missing.pem'), str(Path(_temp.name)/'invalid.pem')):
            if cafile.endswith('invalid.pem'): Path(cafile).write_text('synthetic-private-invalid-cert')
            with patch.dict(os.environ, {'VAULTWARDEN_CA_FILE':cafile}):
                response = self.client.get('/api/vaultwarden/status')
                self.assertEqual(response.status_code,503)
                self.assertNotIn('synthetic-private',response.text)
                self.assertNotIn(cafile,response.text)

    def test_real_tls_trusted_local_cert_passes_untrusted_and_wrong_host_fail(self):
        with temporary_tls_server() as (server_url, cert_file, hits):
            self.service.transport = None
            with patch.dict(os.environ, {'VAULTWARDEN_INTERNAL_URL':server_url,'VAULTWARDEN_CA_FILE':str(cert_file)}):
                response = self.client.get('/api/vaultwarden/status')
                self.assertEqual(response.json()['status'],'running',response.text)
                self.assertEqual(len(hits),1)
            with patch.dict(os.environ, {'VAULTWARDEN_INTERNAL_URL':server_url,'VAULTWARDEN_CA_FILE':''}):
                response = self.client.get('/api/vaultwarden/status')
                self.assertEqual(response.json()['status'],'offline')
                self.assertEqual(len(hits),1,'Untrusted TLS fails before an HTTP request')
            with patch.dict(os.environ, {'VAULTWARDEN_INTERNAL_URL':server_url.replace('localhost','127.0.0.1'),'VAULTWARDEN_CA_FILE':str(cert_file)}):
                response = self.client.get('/api/vaultwarden/status')
                self.assertEqual(response.json()['status'],'offline')
                self.assertEqual(len(hits),1,'Wrong hostname fails before an HTTP request')
                self.assertNotIn(str(cert_file),response.text)


@contextmanager
def temporary_tls_server():
    """A disposable certificate/loopback server; never alter machine trust."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),critical=False)
            .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True,key_encipherment=True,key_cert_sign=True,
                                        crl_sign=True,content_commitment=False,data_encipherment=False,
                                        key_agreement=False,encipher_only=False,decipher_only=False),critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),critical=False)
            .sign(key,hashes.SHA256()))
    with tempfile.TemporaryDirectory(prefix='vault-tls-',dir=_temp.name) as directory:
        cert_file=Path(directory)/'cert.pem';key_file=Path(directory)/'key.pem'
        cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        key_file.chmod(0o600)
        hits=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                body=json.dumps('2026-10-01T14:12:00Z').encode()
                self.send_response(200);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def log_message(self,*args): pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_file,key_file)
        server.socket=context.wrap_socket(server.socket,server_side=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            yield f'https://localhost:{server.server_port}/alive',cert_file,hits
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
