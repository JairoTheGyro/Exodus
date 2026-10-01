"""Isolated Vaultwarden companion routes; no real vault or credentials touched.

Run: docker exec -i sovereign-hub-odysseus-1 python - < tests/vaultwarden_integration.py
Container/gateway checks are covered separately by the deployment smoke suite.
"""
import asyncio
import os
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
            "VAULTWARDEN_INTERNAL_URL": "http://vaultwarden:8080/vault/alive",
            "VAULTWARDEN_PUBLIC_URL": "http://localhost:8092/vault/",
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
                "vault_url": "http://localhost:8092/vault/", "launch_path": "/vault",
                "access_mode": "local", "registration_allowed": False, "embedded": False,
                "start_command": "docker compose -p sovereign-hub up -d --no-deps vaultwarden vaultwarden-gateway",
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
        self.assertEqual(len(self.requests), 2)
        self.assertEqual({str(request.url) for request in self.requests}, {
            "http://vaultwarden:8080/vault/alive", "http://vaultwarden-gateway:8080/vault/alive",
        })
        for request in self.requests:
            for name in ("authorization", "cookie", "x-test-user", "x-test-owner"):
                self.assertNotIn(name, request.headers)
            if request.url.host == "vaultwarden-gateway":
                self.assertEqual(request.headers["host"], "localhost")
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
            self.assertEqual(len(self.requests), 2)
            self.assertNotIn("private server log", result.text)
            self.assertNotIn("synthetic-secret", result.text)

    def test_gateway_probe_cannot_be_retargeted(self):
        for target in ('http://169.254.169.254/vault/alive',
                       'http://vaultwarden-gateway:8081/admin',
                       'http://vaultwarden-gateway:8081/vault/alive?secret=x'):
            with patch.dict(os.environ, {'VAULTWARDEN_GATEWAY_HEALTH_URL': target}):
                response = self.client.get('/api/vaultwarden/status')
                self.assertEqual(response.status_code, 503)
                self.assertNotIn(target, response.text)
        self.requests.clear()
        with patch.dict(os.environ, {'VAULTWARDEN_GATEWAY_HEALTH_URL': 'http://vaultwarden-gateway:8081/vault/alive'}):
            response = self.client.get('/api/vaultwarden/status')
            self.assertEqual(response.json()['status'], 'running')
            self.assertTrue(response.json()['reachable'])
            self.assertIn('docker-compose.vaultwarden-tls.yml', self.client.get('/api/vaultwarden/config').json()['start_command'])
            self.assertTrue(any(r.url.port == 8081 for r in self.requests))

    def test_health_uses_strict_defaults_and_ignores_environment_proxy(self):
        original = httpx.AsyncClient
        with patch.dict(os.environ, {"HTTP_PROXY": "http://proxy.invalid:9000"}):
            with patch("src.vaultwarden_service.httpx.AsyncClient", wraps=original) as client:
                self.assertEqual(self.client.get("/api/vaultwarden/status").json()["status"], "running")
        kwargs = client.call_args.kwargs
        self.assertFalse(kwargs["trust_env"])
        self.assertFalse(kwargs["follow_redirects"])
        self.assertTrue(kwargs.get("verify", True))
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
        self.assertEqual(cancelled, [True, True])

    def test_gateway_outage_is_not_reported_as_a_working_vault_launch(self):
        def transport(request):
            if request.url.host == "vaultwarden-gateway":
                raise httpx.ConnectError("gateway unavailable")
            return httpx.Response(200, json="2026-10-01T14:12:00Z")

        self.service.transport = httpx.MockTransport(transport)
        response = self.client.get("/api/vaultwarden/status")
        self.assertEqual(response.json()["status"], "degraded")
        self.assertEqual(response.json()["checks"], {"vault": "running", "gateway": "offline"})
        self.assertIn("gateway", response.json()["detail"])

    def test_public_url_requires_loopback_http_or_https_and_exact_vault_path(self):
        valid = {
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
                self.assertTrue(response.json()["vault_url"].endswith("/vault/"))
        invalid = (
            "http://vault.example.test/vault/", "http://localhost.evil.test/vault/",
            "https://user:synthetic-secret@example.test/vault/", "//example.test/vault/",
            "javascript:alert(1)", "https://example.test/", "https://example.test/vault/../admin",
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
            "http://169.254.169.254/vault/alive", "https://example.test/vault/alive",
            "http://vaultwarden:8080/admin", "http://vaultwarden:8080/vault/alive?token=secret",
            "http://vaultwarden.evil.test/vault/alive", "http://secret@vaultwarden:8080/vault/alive",
        ):
            with patch.dict(os.environ, {"VAULTWARDEN_INTERNAL_URL": url}):
                response = self.client.get("/api/vaultwarden/status")
                self.assertEqual(response.status_code, 503, url)
                self.assertNotIn(url, response.text)
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
