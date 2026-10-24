"""Exodus "Your AI": per-person AI choice and monthly spending cap."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import AiSpend, ModelEndpoint, Session as DbSession
import routes.ai_budget_routes as routes_mod
import routes.chat_helpers as chat_helpers
import src.ai_budget as budget
import src.ai_policy as policy

ROOT = Path(__file__).resolve().parents[1]
USERS = {"admin": {"is_admin": True}, "mom": {}, "kid": {}}


@pytest.fixture
def factory(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ai.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    made = sessionmaker(bind=engine)
    monkeypatch.setattr(budget, "SessionLocal", made)
    monkeypatch.setattr(chat_helpers, "SessionLocal", made)
    monkeypatch.setattr(budget, "_cache", {})
    return made


def test_spend_accumulates_per_person_and_month(factory):
    budget.record_spend("mom", 0.25)
    budget.record_spend("mom", 0.50)
    budget.record_spend("kid", 1.00)
    for junk in (0, -1, float("nan"), float("inf"), "x", None):
        budget.record_spend("mom", junk)
    budget.record_spend(None, 5)
    assert budget.spent("mom") == pytest.approx(0.75)
    assert budget.spent("kid") == pytest.approx(1.0)
    assert budget.spent("mom", "1999-01") == 0.0


def test_the_lower_cap_applies_and_the_admin_cap_cannot_be_raised(factory):
    budget.save_choice("kid", source="own", self_cap_usd=20)
    budget.set_admin_cap("kid", 5)
    info = budget.status("kid")
    assert (info["self_cap_usd"], info["admin_cap_usd"], info["cap_usd"]) == (20, 5, 5)
    budget.save_choice("kid", self_cap_usd=50)  # the person raising their own cap...
    assert budget.status("kid")["cap_usd"] == 5  # ...doesn't lift the admin's
    budget.save_choice("kid", self_cap_usd=2)
    assert budget.status("kid")["cap_usd"] == 2


@pytest.mark.parametrize("cap", [-1, "lots", float("nan"), 10**9])
def test_caps_are_checked(factory, cap):
    with pytest.raises(budget.BudgetError):
        budget.save_choice("mom", self_cap_usd=cap)


def test_reaching_the_cap_pauses_ai_for_that_person_only(factory, monkeypatch):
    monkeypatch.setattr(policy, "ai_free", lambda owner: False)
    budget.save_choice("kid", self_cap_usd=1)
    budget.record_spend("kid", 0.99)
    policy.require_ai("kid")  # still under
    budget.record_spend("kid", 0.02)
    with pytest.raises(HTTPException) as caught:
        policy.require_ai("kid")
    assert caught.value.status_code == 403 and "$1.00" in caught.value.detail
    policy.require_ai("mom")  # others unaffected
    # A new month starts fresh.
    monkeypatch.setattr(budget, "current_month", lambda now=None: "2999-01")
    budget._cache.clear()
    policy.require_ai("kid")


def test_budget_trouble_never_blocks_ai(factory, monkeypatch):
    monkeypatch.setattr(policy, "ai_free", lambda owner: False)
    monkeypatch.setattr(budget, "status", lambda owner: (_ for _ in ()).throw(RuntimeError("db down")))
    assert budget.pause_reason("kid") is None
    policy.require_ai("kid")


def test_chat_costs_count_toward_the_owner(factory):
    db = factory()
    db.add(DbSession(id="s1", owner="mom", name="Chat", endpoint_url="http://x/v1", model="m"))
    db.commit()
    db.close()
    chat_helpers.accumulate_token_usage("s1", {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.4})
    chat_helpers.accumulate_token_usage("s1", {"input_tokens": 10, "output_tokens": 5})  # local model: free
    assert budget.spent("mom") == pytest.approx(0.4)


@pytest.fixture
def client(factory, monkeypatch, tmp_path):
    modes = {}
    monkeypatch.setattr("core.middleware.auth_disabled", lambda: False)
    monkeypatch.setattr(routes_mod, "_set_mode", lambda owner, mode: modes.__setitem__(owner, mode))
    monkeypatch.setattr("src.home_store.ai_free", lambda owner: modes.get(owner) == "ai-free")
    db = factory()
    db.add_all([
        ModelEndpoint(id="e1", name="Home GPU", base_url="http://gpu:8000/v1", owner=None),
        ModelEndpoint(id="e2", name="Mom's OpenRouter", base_url="https://openrouter.ai/api/v1", owner="mom"),
        ModelEndpoint(id="e3", name="Kid's key", base_url="https://api.example/v1", owner="kid"),
    ])
    db.commit()
    db.close()
    monkeypatch.setattr("core.database.SessionLocal", factory)
    app = FastAPI()
    app.state.auth_manager = SimpleNamespace(is_configured=True, users=USERS,
                                             is_admin=lambda u: bool(USERS.get(u, {}).get("is_admin")))

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.current_user = request.headers.get("x-test-user")
        return await call_next(request)

    app.include_router(routes_mod.setup_ai_budget_routes())
    test_client = TestClient(app, client=("203.0.113.7", 50000))
    test_client.modes = modes
    return test_client


def as_(user):
    return {"x-test-user": user}


def test_choice_api(client):
    mom = client.get("/api/ai-budget", headers=as_("mom")).json()
    assert mom["connections"] == {"own": ["Mom's OpenRouter"], "shared": ["Home GPU"]}
    assert mom["source"] is None and mom["cap_usd"] is None and mom["spent_usd"] == 0

    saved = client.put("/api/ai-budget", json={"source": "own", "self_cap_usd": 15}, headers=as_("mom")).json()
    assert saved["source"] == "own" and saved["cap_usd"] == 15
    assert client.modes["mom"] == "full"
    off = client.put("/api/ai-budget", json={"source": "off"}, headers=as_("mom")).json()
    assert off["source"] == "off" and off["ai_free"] is True and client.modes["mom"] == "ai-free"
    cleared = client.put("/api/ai-budget", json={"clear_cap": True}, headers=as_("mom")).json()
    assert cleared["cap_usd"] is None
    assert client.put("/api/ai-budget", json={"source": "both"}, headers=as_("mom")).status_code == 400
    assert client.put("/api/ai-budget", json={"self_cap_usd": -3}, headers=as_("mom")).status_code == 400
    assert client.get("/api/ai-budget").status_code == 401


def test_admin_member_caps(client):
    assert client.get("/api/ai-budget/members", headers=as_("kid")).status_code == 403
    assert client.put("/api/ai-budget/members/kid", json={"admin_cap_usd": 5}, headers=as_("kid")).status_code == 403
    assert client.put("/api/ai-budget/members/ghost", json={"admin_cap_usd": 5}, headers=as_("admin")).status_code == 404
    capped = client.put("/api/ai-budget/members/kid", json={"admin_cap_usd": 5}, headers=as_("admin")).json()
    assert capped["admin_cap_usd"] == 5 and capped["cap_usd"] == 5
    members = client.get("/api/ai-budget/members", headers=as_("admin")).json()["members"]
    assert [m["username"] for m in members] == ["admin", "kid", "mom"]
    assert next(m for m in members if m["username"] == "kid")["cap_usd"] == 5
    # The member sees the admin's cap and can't remove it.
    kid = client.put("/api/ai-budget", json={"clear_cap": True}, headers=as_("kid")).json()
    assert kid["admin_cap_usd"] == 5 and kid["cap_usd"] == 5


def test_ai_free_accounts_can_still_reach_exodus_non_ai_features():
    for path in ("/api/ai-budget", "/api/ai-budget/members", "/api/spaces", "/api/spaces/x/members",
                 "/api/spaces/documents/d1", "/api/alerts/phone", "/api/alerts/phone/test",
                 "/api/workspace/brand", "/api/services"):
        assert policy.allowed_without_ai(path, "GET"), path
    assert not policy.allowed_without_ai("/api/chat", "POST")


def test_wired():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "from routes.ai_budget_routes import setup_ai_budget_routes" in app
    override = (ROOT / "docker-compose.override.yml").read_text(encoding="utf-8")
    assert "./src/ai_budget.py:/app/src/ai_budget.py:ro" in override
    assert "./routes/ai_budget_routes.py:/app/routes/ai_budget_routes.py:ro" in override
    # Rename support: both tables key on an `owner` column.
    assert hasattr(cdb.AiBudget, "owner") and hasattr(AiSpend, "owner")


def test_your_ai_card_in_a_real_browser():
    import shutil
    import subprocess
    if not shutil.which("node") or not (ROOT / "node_modules" / "playwright").exists():
        pytest.skip("node with the playwright package is required (npm ci)")
    result = subprocess.run(["node", "tests/browser/aiChoice.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: your AI card" in result.stdout


def test_your_ai_card_is_wired():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    panel = html.split('data-settings-panel="account"', 1)[1].split('data-settings-panel=', 1)[0]
    assert 'id="ai-choice-card"' in panel and 'id="ai-choice-rows"' in panel
    assert "mountAiChoice(byId('ai-choice-rows'))" in (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")
    assert "'/static/js/settings/aiChoice.js'" in (ROOT / "static" / "sw.js").read_text(encoding="utf-8")
