"""Exodus "Your AI → My own cloud account" (routes/my_ai_routes.py).

Members connect their own provider account by choosing a provider from a
fixed list and pasting a key. They can never type a web address, so a
connection can't point at internal services. Accounts are private.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import ModelEndpoint
import routes.my_ai_routes as my_ai

ROOT = Path(__file__).resolve().parents[1]
GOOD_KEY = "sk-or-v1-" + "a" * 40


@pytest.fixture
def made(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'ai.db'}", connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    return factory


@pytest.fixture
def client(made, monkeypatch):
    probed = []

    def probe(base_url, api_key):
        probed.append((base_url, api_key))
        return ["openai/gpt-4o-mini", "anthropic/claude-x"] if api_key == GOOD_KEY else []

    monkeypatch.setattr("core.middleware.auth_disabled", lambda: False)
    app = FastAPI()
    app.state.auth_manager = SimpleNamespace(is_configured=True)

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.current_user = request.headers.get("x-test-user")
        return await call_next(request)

    app.include_router(my_ai.setup_my_ai_routes(probe=probe))
    test_client = TestClient(app, client=("203.0.113.7", 50000))
    test_client.probed = probed
    return test_client


def as_(user):
    return {"x-test-user": user}


def test_a_member_connects_a_private_account(client, made):
    providers = client.get("/api/my-ai/providers", headers=as_("kid")).json()["providers"]
    assert {"id": "openrouter", "name": "OpenRouter"} in providers
    added = client.post("/api/my-ai/accounts", json={"provider": "openrouter", "api_key": GOOD_KEY}, headers=as_("kid"))
    assert added.status_code == 200, added.text
    assert added.json()["models"] == 2 and added.json()["provider_name"] == "OpenRouter"
    assert GOOD_KEY not in added.text  # the key is never sent back
    assert client.probed == [("https://openrouter.ai/api/v1", GOOD_KEY)]
    db = made()
    try:
        ep = db.query(ModelEndpoint).one()
        assert ep.owner == "kid" and ep.base_url == "https://openrouter.ai/api/v1" and ep.endpoint_kind == "api"
    finally:
        db.close()
    assert len(client.get("/api/my-ai/accounts", headers=as_("kid")).json()["accounts"]) == 1
    assert client.get("/api/my-ai/accounts", headers=as_("mom")).json()["accounts"] == []  # private


@pytest.mark.parametrize("body", [
    {"provider": "localhost", "api_key": GOOD_KEY},
    {"provider": "http://chromadb:8000", "api_key": GOOD_KEY},
    {"provider": None, "api_key": GOOD_KEY},
    {"provider": "openrouter", "base_url": "http://servicectl:8095", "api_key": GOOD_KEY},
])
def test_members_can_never_choose_an_address(client, made, body):
    response = client.post("/api/my-ai/accounts", json=body, headers=as_("kid"))
    if body.get("provider") == "openrouter":
        # An extra base_url field is ignored: the provider's fixed address is used.
        assert response.status_code == 200
        assert client.probed[-1][0] == "https://openrouter.ai/api/v1"
    else:
        assert response.status_code == 400
        assert client.probed == []


@pytest.mark.parametrize("key", ["", "short", "has space " + "x" * 20, "line\nbreak" + "x" * 20, "x" * 600])
def test_keys_are_checked(client, key):
    assert client.post("/api/my-ai/accounts", json={"provider": "openai", "api_key": key}, headers=as_("kid")).status_code == 400
    assert client.probed == []


def test_a_rejected_key_is_not_saved(client, made):
    response = client.post("/api/my-ai/accounts", json={"provider": "openai", "api_key": "sk-proj-" + "b" * 30}, headers=as_("kid"))
    assert response.status_code == 400 and "didn't accept that key" in response.json()["detail"]
    db = made()
    try:
        assert db.query(ModelEndpoint).count() == 0
    finally:
        db.close()


def test_only_the_owner_removes_it_and_admin_connections_are_off_limits(client, made):
    added = client.post("/api/my-ai/accounts", json={"provider": "openrouter", "api_key": GOOD_KEY}, headers=as_("kid")).json()
    assert client.delete(f"/api/my-ai/accounts/{added['id']}", headers=as_("mom")).status_code == 404
    db = made()
    try:
        # A shared local connection the admin added, and the admin's own local one.
        db.add(ModelEndpoint(id="shared", name="Home GPU", base_url="http://host.docker.internal:1234/v1", owner=None))
        db.add(ModelEndpoint(id="adminlocal", name="Admin box", base_url="http://192.168.1.5:8000/v1", owner="kid"))
        db.commit()
    finally:
        db.close()
    # Not listed and not removable through the member API.
    assert [a["id"] for a in client.get("/api/my-ai/accounts", headers=as_("kid")).json()["accounts"]] == [added["id"]]
    assert client.delete("/api/my-ai/accounts/shared", headers=as_("kid")).status_code == 404
    assert client.delete("/api/my-ai/accounts/adminlocal", headers=as_("kid")).status_code == 404
    assert client.delete(f"/api/my-ai/accounts/{added['id']}", headers=as_("kid")).status_code == 200


def test_limit_and_sign_in(client):
    for _ in range(my_ai.MAX_ACCOUNTS):
        assert client.post("/api/my-ai/accounts", json={"provider": "openrouter", "api_key": GOOD_KEY}, headers=as_("kid")).status_code == 200
    assert client.post("/api/my-ai/accounts", json={"provider": "openrouter", "api_key": GOOD_KEY}, headers=as_("kid")).status_code == 400
    assert client.get("/api/my-ai/accounts").status_code == 401


def test_provider_addresses_are_fixed_https_public_services():
    from src.url_safety import check_outbound_url
    for key, (_, url) in my_ai.PROVIDERS.items():
        assert url.startswith("https://"), key
        assert check_outbound_url(url, block_private=True, resolver=lambda host: ["8.8.8.8"])[0], key


def test_wired():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "from routes.my_ai_routes import setup_my_ai_routes" in app
    assert "./routes/my_ai_routes.py:/app/routes/my_ai_routes.py:ro" in (ROOT / "docker-compose.override.yml").read_text(encoding="utf-8")
    choice = (ROOT / "static" / "js" / "settings" / "aiChoice.js").read_text(encoding="utf-8")
    assert "'/api/my-ai/accounts'" in choice
