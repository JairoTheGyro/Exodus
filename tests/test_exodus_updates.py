"""Exodus one-click updates: src/exodus_updates.py, routes/exodus_update_routes.py,
scripts/update_agent.py. GitHub is faked; nothing is downloaded or installed."""
import asyncio
import importlib.util
import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from src import exodus_updates as eu

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("update_agent_script", ROOT / "scripts" / "update_agent.py")
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)

OLD, NEW = "a" * 40, "b" * 40


def github(runs=None, *, head=NEW, status=200, calls=None):
    runs = [{"name": "tests", "status": "completed", "conclusion": "success"},
            {"name": "codeql", "status": "completed", "conclusion": "skipped"}] if runs is None else runs

    def handler(request):
        if calls is not None:
            calls.append(request.url.path)
        if status != 200:
            return httpx.Response(status, json={})
        path = request.url.path
        if path.endswith("/commits/main"):
            return httpx.Response(200, json={"sha": head, "commit": {"message": "feat: Move to Exodus (#104)\n\nbody",
                                                                     "committer": {"date": "2026-10-25T01:00:00Z"}}})
        if path.endswith(f"/commits/{head}/check-runs"):
            return httpx.Response(200, json={"check_runs": runs})
        if "/compare/" in path:
            return httpx.Response(200, json={"ahead_by": 2, "commits": [
                {"commit": {"message": "feat: one\n\nx"}}, {"commit": {"message": "fix: two"}}]})
        return httpx.Response(404, json={})
    return httpx.MockTransport(handler)


def make(tmp_path, transport, installed=OLD, helper_age=timedelta(seconds=5)):
    folder = tmp_path / "exodus-update"
    folder.mkdir()
    if installed:
        (folder / "installed.json").write_text(json.dumps({"revision": installed, "recorded_at": "2026-10-24T00:00:00+00:00"}))
    if helper_age is not None:
        seen = (datetime.now(timezone.utc) - helper_age).isoformat()
        (folder / "helper.json").write_text(json.dumps({"seen_at": seen, "platform": "darwin"}))
    return eu.Updates(folder, transport=transport), folder


def test_check_finds_a_tested_update_and_its_changes(tmp_path):
    updates, _ = make(tmp_path, github())
    view = asyncio.run(updates.check())
    assert view["latest"]["revision"] == NEW and view["latest"]["tested"] == "passed"
    assert view["latest"]["title"] == "feat: Move to Exodus (#104)"
    assert view["update_available"] and view["ahead_by"] == 2 and view["changes"] == ["fix: two", "feat: one"]
    assert view["compare_url"].endswith(f"/compare/{OLD}...{NEW}") and view["helper"]["online"]


@pytest.mark.parametrize("runs,expected", [
    ([{"name": "t", "status": "completed", "conclusion": "failure"}], "failed"),
    ([{"name": "t", "status": "in_progress", "conclusion": None}], "testing"),
    ([], "unknown"),
    ([{"name": "Python tests", "status": "completed", "conclusion": "success"},
      {"name": "Package static site", "status": "completed", "conclusion": "failure"},
      {"name": "Deploy GitHub Pages", "status": "completed", "conclusion": "failure"}], "passed"),
])
def test_test_results(tmp_path, runs, expected):
    updates, _ = make(tmp_path, github(runs))
    assert asyncio.run(updates.check())["latest"]["tested"] == expected


def test_up_to_date_and_unknown_version(tmp_path):
    updates, _ = make(tmp_path, github(), installed=NEW)
    view = asyncio.run(updates.check())
    assert not view["update_available"] and view["ahead_by"] == 0
    (tmp_path / "x").mkdir()
    updates, _ = make(tmp_path / "x", github(), installed=None)
    view = asyncio.run(updates.check())
    assert view["installed"] is None and not view["update_available"]


def test_manual_checks_are_spaced_but_daily_checks_are_not(tmp_path):
    calls = []
    updates, _ = make(tmp_path, github(calls=calls))
    asyncio.run(updates.check())
    with pytest.raises(eu.UpdateError):
        asyncio.run(updates.check())
    asyncio.run(updates.check(manual=False))
    assert calls.count(f"/repos/{eu.REPOSITORY}/commits/main") == 2


def test_github_trouble_is_reported_not_raised(tmp_path):
    updates, _ = make(tmp_path, github(status=403))
    view = asyncio.run(updates.check())
    assert "limiting" in view["error"] and view["latest"] is None


def test_approve_only_the_newest_tested_version_with_the_helper_running(tmp_path):
    updates, folder = make(tmp_path, github())
    asyncio.run(updates.check())
    for bad in ("c" * 40, "nope"):
        with pytest.raises(eu.UpdateError, match="newest version"):
            updates.approve(bad, "jairo")
    view = updates.approve(NEW, "jairo")
    request = json.loads((folder / "request.json").read_text())
    assert request["target"] == NEW and request["requested_by"] == "jairo" and len(request["id"]) == 16
    assert view["status"]["state"] == "pending"
    with pytest.raises(eu.UpdateError, match="already in progress"):
        updates.approve(NEW, "jairo")


def test_approve_refuses_untested_or_without_helper(tmp_path):
    updates, _ = make(tmp_path, github([{"name": "t", "status": "completed", "conclusion": "failure"}]))
    asyncio.run(updates.check())
    with pytest.raises(eu.UpdateError, match="hasn't passed"):
        updates.approve(NEW, "jairo")
    (tmp_path / "y").mkdir()
    updates, _ = make(tmp_path / "y", github(), helper_age=timedelta(minutes=10))
    asyncio.run(updates.check())
    with pytest.raises(eu.UpdateError, match="helper isn't running"):
        updates.approve(NEW, "jairo")


def test_admins_are_told_once_per_version(tmp_path, monkeypatch):
    updates, _ = make(tmp_path, github())
    asyncio.run(updates.check(manual=False))
    sent, stored = [], []
    async def fake_dispatch(message, **kw):
        sent.append((kw.get("owner"), message))
        return {"status": "sent"}
    monkeypatch.setattr("src.notifications.dispatch_notification", fake_dispatch)
    scheduler = SimpleNamespace(add_notification=lambda *a, **kw: stored.append(kw["owner"]))
    ready = updates.newly_ready()
    asyncio.run(eu.notify_admins(ready, ["jairo", "mom"], scheduler))
    assert [o for o, _ in sent] == ["jairo", "mom"] and stored == ["jairo", "mom"]
    assert "2 changes" in sent[0][1]
    assert updates.newly_ready() is None
    assert not updates.due() and updates.due(datetime.now(timezone.utc) + timedelta(hours=25))


def test_routes_are_for_admins(tmp_path, monkeypatch):
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    import core.middleware as middleware
    from routes.exodus_update_routes import setup_exodus_update_routes
    monkeypatch.setattr(middleware, "auth_disabled", lambda: False)
    updates, _ = make(tmp_path, github())
    app = FastAPI()
    app.state.auth_manager = SimpleNamespace(is_configured=True, is_admin=lambda u: u == "jairo")

    @app.middleware("http")
    async def who(request: Request, call_next):
        request.state.current_user = request.headers.get("x-test-user")
        return await call_next(request)

    app.include_router(setup_exodus_update_routes(updates))
    client = TestClient(app)
    admin, member = {"x-test-user": "jairo"}, {"x-test-user": "mom"}
    assert client.get("/api/updates", headers=member).status_code == 403
    assert client.post("/api/updates/approve", json={"target": NEW}, headers=member).status_code == 403
    assert client.post("/api/updates/check", headers=admin).json()["update_available"]
    assert client.post("/api/updates/check", headers=admin).status_code == 429
    wrong = client.post("/api/updates/approve", json={"target": "c" * 40}, headers=admin)
    assert wrong.status_code == 409 and "newest version" in wrong.json()["detail"]
    assert client.post("/api/updates/approve", json={"target": NEW}, headers=admin).json()["status"]["state"] == "pending"


# ── The update helper on the server ──────────────────────────────────────────

@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    head = {"value": OLD}
    monkeypatch.setattr(agent, "git_head", lambda root=None: head["value"])
    return SimpleNamespace(folder=tmp_path / "data" / "exodus-update", head=head, root=ROOT)


def request_file(folder, target=NEW, age=timedelta(seconds=10), request_id="0123456789abcdef"):
    folder.mkdir(parents=True, exist_ok=True)
    when = (datetime.now(timezone.utc) - age).isoformat()
    (folder / "request.json").write_text(json.dumps({"id": request_id, "target": target, "requested_at": when}))


def test_helper_reports_itself_and_the_installed_version(server):
    assert agent.tick(server.root, run=None) is None
    assert json.loads((server.folder / "installed.json").read_text())["revision"] == OLD
    assert eu.helper(server.folder)["online"] and eu.installed(server.folder)["revision"] == OLD


def test_helper_installs_exactly_the_approved_version(server):
    request_file(server.folder)
    calls = []
    def run(args, **kw):
        calls.append(args)
        server.head["value"] = NEW
        return subprocess.CompletedProcess(args, 0, stdout="Checking GitHub…\nDone\n", stderr="")
    assert agent.tick(server.root, run=run) == "done"
    assert calls[0][1:] == [str(ROOT / "scripts" / "update_local.py"), "--expect", NEW]
    state = eu.status(server.folder)
    assert state["state"] == "done" and "up to date" in state["message"]
    assert not (server.folder / "request.json").exists()
    assert agent.tick(server.root, run=run) is None  # nothing left to do


def test_helper_reports_a_failed_update(server):
    request_file(server.folder)
    run = lambda args, **kw: subprocess.CompletedProcess(args, 1, stdout="Update stopped: GitHub changed after this update was approved.\n", stderr="")
    assert agent.tick(server.root, run=run) == "failed"
    state = eu.status(server.folder)
    assert state["message"].startswith("Update stopped: GitHub changed") and "--rollback" in state["message"]
    assert state["log"] == ["Update stopped: GitHub changed after this update was approved."]


@pytest.mark.parametrize("kwargs", [{"target": "not-a-sha"}, {"age": timedelta(hours=2)}, {"request_id": "x;rm"}])
def test_helper_ignores_bad_or_stale_requests(server, kwargs):
    request_file(server.folder, **kwargs)
    assert agent.tick(server.root, run=lambda *a, **k: pytest.fail("must not update")) is None
    assert not (server.folder / "request.json").exists()


def test_helper_service_files(tmp_path, monkeypatch):
    plist = agent.launchd_plist(Path("/srv/exodus"), "/usr/bin/python3")
    assert "<string>/srv/exodus/scripts/update_agent.py</string>" in plist and "<key>KeepAlive</key><true/>" in plist
    unit = agent.systemd_unit(Path("/srv/exodus"), "/usr/bin/python3")
    assert "ExecStart=/usr/bin/python3 /srv/exodus/scripts/update_agent.py run" in unit and "Restart=always" in unit
    assert agent.install(run=None, system="Windows") == 1
    monkeypatch.setattr(agent.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(agent, "shutil_which", lambda name: "/usr/bin/docker")
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    calls = []
    run = lambda args, **kw: calls.append(args) or subprocess.CompletedProcess(args, 0, stdout="", stderr="")
    assert agent.install(run=run, system="Linux") == 0
    assert (tmp_path / ".config/systemd/user/exodus-update-helper.service").exists()
    assert ["systemctl", "--user", "enable", "--now", "exodus-update-helper.service"] in calls
    assert agent.uninstall(run=run, system="Linux") == 0
    assert not (tmp_path / ".config/systemd/user/exodus-update-helper.service").exists()


def test_updates_card_in_a_real_browser():
    if not shutil.which("node") or not (ROOT / "node_modules" / "playwright").exists():
        pytest.skip("node with the playwright package is required (npm ci)")
    result = subprocess.run(["node", "tests/browser/exodusUpdates.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: updates card" in result.stdout


def test_wired():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "from routes.exodus_update_routes import setup_exodus_update_routes" in app
    assert "_exodus_update_loop(" in app
    override = (ROOT / "docker-compose.override.yml").read_text(encoding="utf-8")
    assert "./src/exodus_updates.py:/app/src/exodus_updates.py:ro" in override
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    panel = html.split('data-settings-panel="licenses"', 1)[1].split('data-settings-panel=', 1)[0]
    assert 'id="exodus-updates-card" hidden' in panel
    assert "mountUpdates(byId('exodus-updates-rows'))" in (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")
    assert "'/static/js/settings/exodusUpdates.js'" in (ROOT / "static" / "sw.js").read_text(encoding="utf-8")
    from src.ai_policy import allowed_without_ai
    assert allowed_without_ai("/api/updates/check", "POST")
