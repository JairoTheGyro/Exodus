"""Exodus Services manager routes (routes/services_routes.py).

The helper is faked with httpx.MockTransport, so nothing touches Docker.
"""
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.services_routes as services

ROOT = Path(__file__).resolve().parents[1]
ADMIN = {"x-test-user": "admin"}
MEMBER = {"x-test-user": "alice"}
TOKEN = "k" * 40


def build(tmp_path, monkeypatch, handler=None, token=TOKEN):
    path = tmp_path / "token"
    if token is not None:
        path.write_text(token)
    monkeypatch.setattr(services, "TOKEN_PATH", str(path))
    monkeypatch.setattr("core.middleware.auth_disabled", lambda: False)
    seen = []

    def record(request):
        seen.append(request)
        return handler(request) if handler else httpx.Response(500)

    factory = lambda: httpx.AsyncClient(base_url="http://servicectl:8095", transport=httpx.MockTransport(record))
    app = FastAPI()
    app.state.auth_manager = SimpleNamespace(is_configured=True, is_admin=lambda user: user == "admin")

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.current_user = request.headers.get("x-test-user")
        return await call_next(request)

    app.include_router(services.setup_services_routes(client_factory=factory))
    return TestClient(app), seen


def listing(request):
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    return httpx.Response(200, json={"services": [
        {"name": "searxng", "label": "SearXNG", "state": "running"},
        {"name": "sneaky", "label": "Not allowed", "state": "running"},
    ]})


def test_members_cannot_see_or_change_services(tmp_path, monkeypatch):
    client, seen = build(tmp_path, monkeypatch, listing)
    assert client.get("/api/services", headers=MEMBER).status_code == 403
    assert client.post("/api/services/searxng/stop", headers=MEMBER).status_code == 403
    assert seen == []


def test_without_the_add_on_the_screen_explains_how_to_enable_it(tmp_path, monkeypatch):
    client, seen = build(tmp_path, monkeypatch, listing, token=None)
    data = client.get("/api/services", headers=ADMIN).json()
    assert data["available"] is False and data["reason"] == "not_enabled"
    assert "docker/service-manager.yml" in data["hint"]
    response = client.post("/api/services/searxng/stop", headers=ADMIN)
    assert response.status_code == 503 and "docker/service-manager.yml" in response.json()["detail"]
    assert seen == []


def test_unreachable_helper_is_reported(tmp_path, monkeypatch):
    def down(request):
        raise httpx.ConnectError("no route", request=request)

    client, _ = build(tmp_path, monkeypatch, down)
    assert client.get("/api/services", headers=ADMIN).json()["reason"] == "unreachable"
    assert client.post("/api/services/searxng/stop", headers=ADMIN).status_code == 503


def test_listing_forwards_the_token_and_drops_unknown_services(tmp_path, monkeypatch):
    client, _ = build(tmp_path, monkeypatch, listing)
    data = client.get("/api/services", headers=ADMIN).json()
    assert data["available"] is True
    assert [s["name"] for s in data["services"]] == ["searxng"]


def test_actions_are_forwarded_with_delete_data_only_for_remove(tmp_path, monkeypatch):
    client, seen = build(tmp_path, monkeypatch, lambda r: httpx.Response(202, json={}))
    assert client.post("/api/services/ntfy/remove", json={"delete_data": True}, headers=ADMIN).status_code == 202
    assert client.post("/api/services/ntfy/stop", json={"delete_data": True}, headers=ADMIN).status_code == 202
    assert client.post("/api/services/ntfy/remove", headers=ADMIN).status_code == 202
    assert [(r.url.path, r.read()) for r in seen] == [
        ("/services/ntfy/remove", b'{"delete_data":true}'),
        ("/services/ntfy/stop", b'{"delete_data":false}'),
        ("/services/ntfy/remove", b'{"delete_data":false}'),
    ]
    assert all(r.headers["authorization"] == f"Bearer {TOKEN}" for r in seen)


@pytest.mark.parametrize("path", ["/api/services/odysseus/stop", "/api/services/servicectl/stop",
                                  "/api/services/searxng/exec"])
def test_unknown_services_and_actions_are_never_forwarded(tmp_path, monkeypatch, path):
    client, seen = build(tmp_path, monkeypatch, lambda r: httpx.Response(202, json={}))
    assert client.post(path, headers=ADMIN).status_code == 404
    assert seen == []


@pytest.mark.parametrize("code,expected", [(409, 409), (500, 502), (401, 502)])
def test_helper_errors_become_clear_answers(tmp_path, monkeypatch, code, expected):
    client, _ = build(tmp_path, monkeypatch, lambda r: httpx.Response(code, json={}))
    response = client.post("/api/services/searxng/start", headers=ADMIN)
    assert response.status_code == expected
    if expected == 409:
        assert "already busy" in response.json()["detail"]


def test_routes_are_registered_and_mounted():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "from routes.services_routes import setup_services_routes" in app
    assert "app.include_router(setup_services_routes())" in app
    override = (ROOT / "docker-compose.override.yml").read_text(encoding="utf-8")
    assert "./routes/services_routes.py:/app/routes/services_routes.py:ro" in override


def test_docker_access_lives_only_in_the_opt_in_overlay():
    overlay = (ROOT / "docker" / "service-manager.yml").read_text(encoding="utf-8")
    assert "/var/run/docker.sock:/var/run/docker.sock" in overlay
    assert "servicectl-token:/run/servicectl:ro" in overlay  # the app only reads the token
    assert "ports:" not in overlay  # helper is internal-only
    for name in ("docker-compose.yml", "docker-compose.override.yml"):
        assert "docker.sock" not in (ROOT / name).read_text(encoding="utf-8")
