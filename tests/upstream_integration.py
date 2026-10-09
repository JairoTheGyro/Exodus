"""Isolated upstream API checks, with a mock GitHub transport and disposable data.

Run using the installed Docker image with the checkout mounted read-only.
"""
import os
import base64
import tempfile
import unittest
from types import SimpleNamespace

_temp = tempfile.TemporaryDirectory(prefix="exodus-upstream-tests-")
os.environ["ODYSSEUS_DATA_DIR"] = _temp.name
os.environ["DATABASE_URL"] = "sqlite:///" + _temp.name + "/test.db"
os.environ["AUTH_ENABLED"] = "true"
os.environ["LOCALHOST_BYPASS"] = "false"

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routes.upstream_routes import setup_upstream_routes
from src.upstream_updates import UpdateTracker

BASE, HEAD, OLD = "a" * 40, "b" * 40, "c" * 40
PROJECT = {"id": "example", "name": "Example", "repository": "example/public", "branch": "dev",
           "used_commit": BASE, "used_date": "2026-09-14", "used_note": "Local modifications"}


def commit(sha):
    return {"sha": sha, "commit": {"message": "Add feature\n\n<script>alert('untrusted')</script>",
            "committer": {"date": "2026-09-25T12:00:00Z"}}}


class UpstreamTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=_temp.name)
        self.calls = []
        self.failure = None
        self.compare_status = "ahead"

        def github(request):
            self.calls.append(request)
            self.assertEqual(request.url.host, "api.github.com")
            self.assertNotIn("authorization", request.headers)
            if self.failure == "offline":
                raise httpx.ConnectError("Offline", request=request)
            if self.failure == "rate":
                return httpx.Response(429)
            path = request.url.path
            if "/contents/" in path:
                self.assertEqual(request.url.params["ref"], HEAD)
                return httpx.Response(200, json={"content": base64.b64encode(b'APP_VERSION = "2.0.0"\nraise Exception("must never execute upstream code")').decode()})
            if "/compare/" in path:
                if self.failure == "compare":
                    return httpx.Response(404)
                return httpx.Response(200, json={"status": self.compare_status, "ahead_by": 2, "behind_by": 0, "total_commits": 2})
            if path.endswith("/releases"):
                return httpx.Response(200, json=[] if self.failure == "no-releases" else [{"tag_name": "v2", "name": "Version 2", "body": "Added X\nRemoved Y", "published_at": "2026-09-25T00:00:00Z"}])
            if path.endswith("/commits"):
                if request.url.params.get("page") == "2":
                    self.assertEqual(request.url.params["sha"], HEAD)
                    return httpx.Response(200, json=[commit(OLD)])
                return httpx.Response(200, json=[commit(HEAD)], headers={"link": '<https://not-followed.invalid>; rel="next"'})
            if path.endswith("/commits/" + HEAD):
                return httpx.Response(200, json={**commit(HEAD), "files": [
                    {"filename": "new.py", "status": "added", "additions": 4, "deletions": 0},
                    {"filename": "old.py", "status": "removed", "additions": 0, "deletions": 8}],
                    "stats": {"additions": 4, "deletions": 8}}, headers={"link": '<https://not-followed.invalid>; rel="next"'})
            raise AssertionError(path)

        self.tracker = UpdateTracker(self.directory.name, [PROJECT], httpx.MockTransport(github))
        app = FastAPI()
        app.state.auth_manager = SimpleNamespace(is_configured=True, is_admin=lambda user: user == "admin")

        @app.middleware("http")
        async def identity(request, call_next):
            request.state.current_user = request.headers.get("x-test-user")
            request.state.api_token = request.headers.get("x-test-token") == "yes"
            return await call_next(request)

        app.include_router(setup_upstream_routes(self.tracker))
        self.client = TestClient(app)
        self.headers = {"x-test-user": "admin"}

    def tearDown(self):
        self.client.close()
        self.directory.cleanup()

    def check(self):
        return self.client.post("/api/upstream/example/check", headers=self.headers)

    def allow_recheck(self):
        cache = self.tracker.read("example")
        cache["last_attempt"] = "2000-01-01T00:00:00+00:00"
        self.tracker.save("example", cache)

    def test_initial_read_is_offline_and_baseline_is_exact(self):
        data = self.client.get("/api/upstream", headers=self.headers).json()
        self.assertIsNone(data["projects"][0]["snapshot"])
        self.assertEqual(data["projects"][0]["project"]["used_commit"], BASE)
        self.assertEqual(self.calls, [])

    def test_shipped_services_have_exact_recorded_references_without_network(self):
        tracker=UpdateTracker(self.directory.name,transport=httpx.MockTransport(
            lambda request: self.fail('Reading installed references must remain offline')))
        expected={'odysseus','vaultwarden','deepseek-harness','searxng','chromadb','ntfy'}
        self.assertTrue(expected.issubset(tracker.projects))
        for name in expected:
            view=tracker.view(name)
            self.assertIsNone(view['snapshot'])
            self.assertRegex(view['project']['used_commit'],r'^[0-9a-f]{40}$')
        for name in ('vaultwarden','searxng','chromadb','ntfy'):
            project=tracker.project(name)
            self.assertRegex(project['used_image'],r'^[a-z0-9_./-]+@sha256:[0-9a-f]{64}$')
            self.assertEqual(project['observed_at'],'2026-10-06')
        self.assertIn('not a digest pin',tracker.project('vaultwarden')['used_note'])
        self.assertIn('not a verified build provenance claim',tracker.project('chromadb')['used_note'])

    def test_check_records_real_comparison_and_does_not_advance_baseline(self):
        data = self.check().json()
        self.assertEqual(data["project"]["used_commit"], BASE)
        self.assertEqual(data["snapshot"]["head"], HEAD)
        self.assertEqual(data["snapshot"]["comparison"]["ahead_by"], 2)
        self.assertIn("Removed Y", data["snapshot"]["releases"][0]["notes"])

    def test_offline_failure_preserves_previous_success(self):
        before = self.check().json()["snapshot"]
        self.allow_recheck()
        self.failure = "offline"
        after = self.check().json()
        self.assertEqual(after["snapshot"], before)
        self.assertIn("Could not reach", after["error"])

    def test_rate_limit_is_not_reported_as_up_to_date(self):
        self.failure = "rate"
        data = self.check().json()
        self.assertIsNone(data["snapshot"])
        self.assertIn("limited", data["error"])

    def test_repeated_check_does_not_spam_github(self):
        self.check()
        count = len(self.calls)
        self.assertEqual(self.check().status_code, 503)
        self.assertEqual(len(self.calls), count)

    def test_missing_comparison_keeps_history_with_explicit_unknown(self):
        self.failure = "compare"
        snapshot = self.check().json()["snapshot"]
        self.assertIsNone(snapshot["comparison"])
        self.assertTrue(snapshot["comparison_error"])
        self.assertTrue(snapshot["commits"])

    def test_divergence_is_preserved(self):
        self.compare_status = "diverged"
        self.assertEqual(self.check().json()["snapshot"]["comparison"]["status"], "diverged")

    def test_absent_releases_do_not_create_fake_version(self):
        self.failure = "no-releases"
        data = self.check().json()["snapshot"]
        self.assertEqual(data["releases"], [])
        self.assertEqual(data["head"], HEAD)

    def test_older_pages_are_snapshot_anchored_and_cached(self):
        self.check()
        url = "/api/upstream/example/history?page=2"
        count = len(self.calls)
        self.assertEqual(self.client.get(url, headers=self.headers).status_code, 503)
        self.assertEqual(len(self.calls), count)
        first = self.client.post(url, headers=self.headers).json()
        self.assertEqual(first["commits"][0]["sha"], OLD)
        count = len(self.calls)
        self.failure = "offline"
        self.assertEqual(self.client.get(url, headers=self.headers).json(), first)
        self.assertEqual(len(self.calls), count)

    def test_file_additions_removals_and_truncation_are_honest(self):
        url = f"/api/upstream/example/commits/{HEAD}"
        data = self.client.post(url, headers=self.headers).json()
        self.assertEqual([f["status"] for f in data["files"]], ["added", "removed"])
        self.assertTrue(data["more_files"])
        count = len(self.calls)
        self.assertEqual(self.client.get(url, headers=self.headers).json(), data)
        self.assertEqual(len(self.calls), count)

    def test_auth_and_manifest_restrictions(self):
        self.assertEqual(self.client.get("/api/upstream").status_code, 401)
        user = {"x-test-user": "member"}
        self.assertFalse(self.client.get("/api/upstream", headers=user).json()["can_check"])
        self.assertEqual(self.client.post("/api/upstream/example/check", headers=user).status_code, 403)
        self.assertEqual(self.client.post("/api/upstream/untracked/check", headers=self.headers).status_code, 404)
        self.assertEqual(self.client.post("/api/upstream/example/commits/bad", headers=self.headers).status_code, 503)
        self.assertEqual(self.client.post("/api/upstream/example/history?page=0", headers=self.headers).status_code, 422)
        self.assertEqual(self.calls, [])

    def test_cache_survives_restart_and_invalidates_changed_baseline(self):
        self.check()
        fresh = UpdateTracker(self.directory.name, [PROJECT])
        self.assertEqual(fresh.view("example")["snapshot"]["head"], HEAD)
        changed = UpdateTracker(self.directory.name, [{**PROJECT, "used_commit": OLD}])
        self.assertIsNone(changed.view("example")["snapshot"])

    def test_declared_version_read_as_text_at_exact_head(self):
        self.tracker.projects["example"] = {**PROJECT, "version_file": "src/constants.py"}
        self.assertEqual(self.check().json()["snapshot"]["version"], "2.0.0")

    def test_branch_change_invalidates_old_snapshot(self):
        self.check()
        changed = UpdateTracker(self.directory.name, [{**PROJECT, "branch": "main"}])
        self.assertIsNone(changed.view("example")["snapshot"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
