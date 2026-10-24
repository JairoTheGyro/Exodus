"""Exodus private phone alerts: one ntfy topic per account (src/personal_alerts.py)."""
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.notifications as notifications
import src.personal_alerts as alerts
import routes.note_routes as note_routes
import routes.personal_alerts_routes as alert_routes

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def store(monkeypatch):
    prefs = {}
    monkeypatch.setattr(alerts, "_load", lambda owner: dict(prefs.get(owner, {})))
    monkeypatch.setattr(alerts, "_save", lambda owner, value: prefs.__setitem__(owner, dict(value)))
    monkeypatch.setattr(alerts, "has_accounts", lambda: True)
    return prefs


def test_each_account_gets_its_own_private_topic(store):
    mom = alerts.personal_topic("mom")
    dad = alerts.personal_topic("dad")
    assert mom != dad
    assert alerts.TOPIC_RE.fullmatch(mom) and alerts.TOPIC_RE.fullmatch(dad)
    assert len(mom) >= len("exodus-") + 20  # long enough to be unguessable
    assert "mom" not in mom  # the address doesn't reveal who it belongs to
    assert alerts.personal_topic("mom") == mom  # stable
    assert store["mom"][alerts.PREF_KEY] == mom


def test_reset_gives_a_new_topic(store):
    old = alerts.personal_topic("mom")
    new = alerts.reset_topic("mom")
    assert new != old and alerts.personal_topic("mom") == new


def test_a_tampered_topic_is_replaced(store):
    store["mom"] = {alerts.PREF_KEY: "Reminders"}  # someone else's shared topic
    topic = alerts.personal_topic("mom")
    assert topic != "Reminders" and alerts.TOPIC_RE.fullmatch(topic)


def test_single_user_installs_keep_the_shared_topic(store, monkeypatch):
    assert alerts.personal_topic(None) is None
    assert alerts.personal_topic("owner@localhost") is None
    monkeypatch.setattr(alerts, "has_accounts", lambda: False)
    assert alerts.personal_topic("mom") is None


def test_public_server_url(monkeypatch):
    monkeypatch.setenv("NTFY_PUBLIC_URL", "http://100.64.0.5:8091/")
    assert alerts.public_server_url() == "http://100.64.0.5:8091"


@pytest.fixture
def sent(monkeypatch):
    urls = []

    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(200)

    monkeypatch.setenv("NTFY_ENABLED", "true")
    monkeypatch.setattr(notifications, "_destination", lambda: ("http://ntfy:8080", ""))
    monkeypatch.setattr(notifications, "_validated_transport", lambda url: httpx.MockTransport(handler))
    return urls


async def test_alerts_go_to_the_owners_topic(store, sent, monkeypatch):
    monkeypatch.setenv("NTFY_DEFAULT_TOPIC", "exodus-alerts")
    assert (await notifications.dispatch_notification("hi", owner="mom"))["status"] == "sent"
    assert (await notifications.dispatch_notification("hi", owner="dad"))["status"] == "sent"
    assert (await notifications.dispatch_notification("hi"))["status"] == "sent"
    assert (await notifications.dispatch_notification("hi", owner="mom", topic="explicit"))["status"] == "sent"
    assert sent == [
        f"http://ntfy:8080/{alerts.personal_topic('mom')}",
        f"http://ntfy:8080/{alerts.personal_topic('dad')}",
        "http://ntfy:8080/exodus-alerts",
        "http://ntfy:8080/explicit",
    ]


def test_reminders_use_the_personal_topic(store, monkeypatch):
    settings = {"reminder_ntfy_topic": "Reminders"}
    assert note_routes._reminder_topic("mom", settings) == alerts.personal_topic("mom")
    assert note_routes._reminder_topic("", settings) == "Reminders"
    monkeypatch.setattr(alerts, "has_accounts", lambda: False)
    assert note_routes._reminder_topic("mom", settings) == "Reminders"


@pytest.fixture
def client(store, sent, monkeypatch):
    monkeypatch.setattr("core.middleware.auth_disabled", lambda: False)
    monkeypatch.setenv("NTFY_PUBLIC_URL", "http://phone.example:8091")
    app = FastAPI()
    app.state.auth_manager = SimpleNamespace(is_configured=True)

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.current_user = request.headers.get("x-test-user")
        return await call_next(request)

    app.include_router(alert_routes.setup_personal_alerts_routes())
    return TestClient(app, client=("203.0.113.7", 50000))


def test_settings_api(client, sent):
    mom = client.get("/api/alerts/phone", headers={"x-test-user": "mom"}).json()
    dad = client.get("/api/alerts/phone", headers={"x-test-user": "dad"}).json()
    assert mom["personal"] is True and mom["server"] == "http://phone.example:8091"
    assert mom["subscribe_url"] == f"http://phone.example:8091/{mom['topic']}"
    assert mom["topic"] != dad["topic"]

    assert client.post("/api/alerts/phone/test", headers={"x-test-user": "mom"}).json()["status"] == "sent"
    assert sent[-1].endswith("/" + mom["topic"])

    renewed = client.post("/api/alerts/phone/reset", headers={"x-test-user": "mom"}).json()
    assert renewed["topic"] != mom["topic"]
    assert client.get("/api/alerts/phone").status_code == 401


def test_wired_into_the_app_and_compose():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "from routes.personal_alerts_routes import setup_personal_alerts_routes" in app
    override = (ROOT / "docker-compose.override.yml").read_text(encoding="utf-8")
    assert "./src/personal_alerts.py:/app/src/personal_alerts.py:ro" in override
    assert "./routes/personal_alerts_routes.py:/app/routes/personal_alerts_routes.py:ro" in override
    for name in ("docker-compose.yml", "docker-compose.gpu-amd.yml", "docker-compose.gpu-nvidia.yml"):
        assert "NTFY_PUBLIC_URL=${NTFY_PUBLIC_URL:-http://localhost:8091}" in (ROOT / name).read_text(encoding="utf-8")


def test_phone_alerts_card_in_a_real_browser():
    import shutil
    import subprocess
    if not shutil.which("node") or not (ROOT / "node_modules" / "playwright").exists():
        pytest.skip("node with the playwright package is required (npm ci)")
    result = subprocess.run(["node", "tests/browser/phoneAlerts.mjs"], cwd=ROOT,
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: phone alerts card" in result.stdout


def test_phone_alerts_card_is_wired():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    panel = html.split('data-settings-panel="account"', 1)[1].split('data-settings-panel=', 1)[0]
    assert 'id="phone-alerts-card"' in panel and 'id="phone-alerts-rows"' in panel
    settings = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")
    assert "mountPhoneAlerts(byId('phone-alerts-rows'))" in settings
    assert "'/static/js/settings/phoneAlerts.js'" in (ROOT / "static" / "sw.js").read_text(encoding="utf-8")
