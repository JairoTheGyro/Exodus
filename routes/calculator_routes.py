# routes/calculator_routes.py
# Same-origin currency rates for the Calculator tool window's Convert mode.
#
# The browser only talks to Exodus (CSP connect-src 'self'), so this route
# fetches the free ExchangeRate-API feed (https://open.er-api.com, no key,
# USD base) on the server and returns a validated copy. It runs only when the
# user picks the Currency category in Convert; nothing else in Calculator uses
# the network. Rates are cached in memory for six hours and the last good copy
# is served (marked stale) when the feed is unreachable, so offline use shows an
# honest "Updated …" age instead of failing outright.
import asyncio
import logging
import re
import time

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.auth_helpers import require_user

logger = logging.getLogger(__name__)

RATES_URL = "https://open.er-api.com/v6/latest/USD"
RATES_SOURCE = "ExchangeRate-API (open.er-api.com)"
CACHE_SECONDS = 6 * 3600
_MAX_CURRENCIES = 400
_CODE_RE = re.compile(r"^[A-Z]{3}$")

_cache = {"fetched": 0.0, "data": None}
_lock = asyncio.Lock()


def validate_rates(payload) -> dict | None:
    """Return {"updated": int, "rates": {code: float}} or None when malformed."""
    if not isinstance(payload, dict) or payload.get("result") != "success":
        return None
    rates = payload.get("rates")
    updated = payload.get("time_last_update_unix")
    if not isinstance(rates, dict) or not isinstance(updated, (int, float)) or isinstance(updated, bool):
        return None
    clean = {}
    for code, value in rates.items():
        if not isinstance(code, str) or not _CODE_RE.match(code):
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        value = float(value)
        if value > 0 and value < 1e12:
            clean[code] = value
        if len(clean) >= _MAX_CURRENCIES:
            break
    if "USD" not in clean or len(clean) < 2:
        return None
    return {"updated": int(updated), "rates": clean}


async def _fetch() -> dict | None:
    async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
        r = await client.get(RATES_URL, headers={"Accept": "application/json"})
    if r.status_code != 200 or len(r.content) > 512 * 1024:
        return None
    return validate_rates(r.json())


def setup_calculator_routes() -> APIRouter:
    router = APIRouter(prefix="/api/calculator", tags=["calculator"])

    @router.get("/rates")
    async def currency_rates(_user: str = Depends(require_user)):
        async with _lock:
            now = time.time()
            data = _cache["data"]
            if data is None or now - _cache["fetched"] > CACHE_SECONDS:
                try:
                    fresh = await _fetch()
                except Exception as e:  # network, DNS, JSON — fall back to the cached copy
                    logger.warning("calculator rates fetch failed: %s", e)
                    fresh = None
                if fresh is not None:
                    _cache["data"] = data = fresh
                    _cache["fetched"] = now
            if data is None:
                return JSONResponse({"error": "Currency rates unavailable"}, status_code=503,
                                    headers={"Cache-Control": "no-store"})
            stale = now - _cache["fetched"] > CACHE_SECONDS
            return JSONResponse(
                {"source": RATES_SOURCE, "base": "USD", "updated": data["updated"],
                 "rates": data["rates"], "stale": stale},
                headers={"Cache-Control": "no-store"},
            )

    return router
