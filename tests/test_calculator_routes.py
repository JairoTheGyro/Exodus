"""Calculator currency-rate route (`routes/calculator_routes.py`).

The browser keeps `connect-src 'self'`, so Convert → Currency asks Exodus,
which fetches ExchangeRate-API server-side. These tests never touch the
network: the upstream fetch is replaced with fixtures.
"""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.calculator_routes as calc
from src.auth_helpers import require_user

_GOOD = {
    "result": "success",
    "time_last_update_unix": 1792195201,
    "rates": {"USD": 1, "EUR": 0.92, "JPY": 151.3, "bad": 5, "XXX": -1, "GBP": True, "MXN": "17"},
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(calc, "_cache", {"fetched": 0.0, "data": None})
    monkeypatch.setattr(calc, "_lock", asyncio.Lock())
    app = FastAPI()
    app.include_router(calc.setup_calculator_routes())
    app.dependency_overrides[require_user] = lambda: "practice-user"
    return TestClient(app)


def test_validate_rates_keeps_only_well_formed_codes():
    out = calc.validate_rates(_GOOD)
    assert out == {"updated": 1792195201, "rates": {"USD": 1.0, "EUR": 0.92, "JPY": 151.3}}
    assert calc.validate_rates({"result": "error"}) is None
    assert calc.validate_rates({"result": "success", "time_last_update_unix": 1, "rates": {"EUR": 1}}) is None
    assert calc.validate_rates("nope") is None


def test_rates_are_fetched_once_then_cached(client, monkeypatch):
    calls = []

    async def fake_fetch():
        calls.append(1)
        return calc.validate_rates(_GOOD)

    monkeypatch.setattr(calc, "_fetch", fake_fetch)
    first = client.get("/api/calculator/rates")
    second = client.get("/api/calculator/rates")
    assert first.status_code == 200 and second.status_code == 200
    body = first.json()
    assert body["base"] == "USD" and body["rates"]["EUR"] == 0.92 and body["stale"] is False
    assert body["source"] == calc.RATES_SOURCE
    assert first.headers["cache-control"] == "no-store"
    assert len(calls) == 1


def test_offline_serves_last_good_copy_marked_stale(client, monkeypatch):
    async def ok():
        return calc.validate_rates(_GOOD)

    async def down():
        raise OSError("no network")

    monkeypatch.setattr(calc, "_fetch", ok)
    assert client.get("/api/calculator/rates").status_code == 200
    calc._cache["fetched"] -= calc.CACHE_SECONDS + 1        # age the cache past its lifetime
    monkeypatch.setattr(calc, "_fetch", down)
    r = client.get("/api/calculator/rates")
    assert r.status_code == 200
    assert r.json()["stale"] is True and r.json()["rates"]["JPY"] == 151.3


def test_unavailable_without_any_copy(client, monkeypatch):
    async def down():
        raise OSError("no network")

    monkeypatch.setattr(calc, "_fetch", down)
    r = client.get("/api/calculator/rates")
    assert r.status_code == 503
    assert r.json() == {"error": "Currency rates unavailable"}


def test_route_requires_a_signed_in_user():
    router = calc.setup_calculator_routes()
    route = next(r for r in router.routes if getattr(r, "path", "").endswith("/rates"))
    assert any(d.call is require_user for d in route.dependant.dependencies)


def test_router_is_registered_in_app():
    src = open(calc.__file__.replace("routes/calculator_routes.py", "app.py"), encoding="utf-8").read()
    assert "app.include_router(setup_calculator_routes())" in src
