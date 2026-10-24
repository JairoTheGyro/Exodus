"""Exodus: each person's AI choice and monthly AI spending cap.

- Choice: "shared" (the household's AI connections), "own" (their own cloud
  account), or "off" (AI-free, the existing per-account workspace mode).
- Cap: a monthly US-dollar limit. The person can set one; an admin can set
  one per member that the member can't raise. The lower one applies.
- Spend: estimated cost of chat and agent turns (src/model_pricing.py; local
  models cost nothing), counted per calendar month in UTC.

When the cap is reached, AI pauses for that person (require_ai raises) until
the month changes or the cap is raised. Errors reading the budget never block
AI: the cap is a convenience limit, not a security boundary.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from core.database import AiBudget, AiSpend, SessionLocal

logger = logging.getLogger(__name__)
SOURCES = ("shared", "own", "off")
MAX_CAP = 100000.0
_cache: dict[str, tuple[float, Optional[str]]] = {}
_cache_lock = threading.Lock()
CACHE_SECONDS = 10.0


class BudgetError(ValueError):
    pass


def current_month(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def _clean_cap(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        cap = float(value)
    except (TypeError, ValueError):
        raise BudgetError("The cap must be a number of dollars.")
    if not math.isfinite(cap) or cap < 0 or cap > MAX_CAP:
        raise BudgetError("The cap must be between $0 and $100,000.")
    return round(cap, 2)


def effective_cap(row: Optional[AiBudget]) -> Optional[float]:
    caps = [c for c in (getattr(row, "self_cap_usd", None), getattr(row, "admin_cap_usd", None)) if c is not None]
    return min(caps) if caps else None


def spent(owner: str, month: Optional[str] = None, db=None) -> float:
    own = db is None
    db = db or SessionLocal()
    try:
        row = db.query(AiSpend).filter(AiSpend.owner == owner, AiSpend.month == (month or current_month())).first()
        return float(row.cost_usd or 0.0) if row else 0.0
    finally:
        if own:
            db.close()


def status(owner: str) -> dict:
    db = SessionLocal()
    try:
        row = db.query(AiBudget).filter(AiBudget.owner == owner).first()
        month = current_month()
        used = spent(owner, month, db)
        cap = effective_cap(row)
        return {
            "source": getattr(row, "source", None),
            "self_cap_usd": getattr(row, "self_cap_usd", None),
            "admin_cap_usd": getattr(row, "admin_cap_usd", None),
            "cap_usd": cap,
            "month": month,
            "spent_usd": round(used, 4),
            "paused": cap is not None and used >= cap,
        }
    finally:
        db.close()


def _forget(owner: str) -> None:
    with _cache_lock:
        _cache.pop(owner, None)


def save_choice(owner: str, *, source=None, self_cap_usd="__keep__") -> dict:
    if source is not None and source not in SOURCES:
        raise BudgetError("Choose shared, own or off.")
    db = SessionLocal()
    try:
        row = db.query(AiBudget).filter(AiBudget.owner == owner).first()
        if row is None:
            row = AiBudget(owner=owner)
            db.add(row)
        if source is not None:
            row.source = source
        if self_cap_usd != "__keep__":
            row.self_cap_usd = _clean_cap(self_cap_usd)
        db.commit()
    finally:
        db.close()
    _forget(owner)
    return status(owner)


def set_admin_cap(owner: str, cap) -> dict:
    db = SessionLocal()
    try:
        row = db.query(AiBudget).filter(AiBudget.owner == owner).first()
        if row is None:
            row = AiBudget(owner=owner)
            db.add(row)
        row.admin_cap_usd = _clean_cap(cap)
        db.commit()
    finally:
        db.close()
    _forget(owner)
    return status(owner)


def record_spend(owner: Optional[str], cost_usd) -> None:
    """Add an estimated cost to this month's total. Never raises."""
    try:
        cost = float(cost_usd or 0.0)
        if not owner or not math.isfinite(cost) or cost <= 0:
            return
        month = current_month()
        db = SessionLocal()
        try:
            row = db.query(AiSpend).filter(AiSpend.owner == owner, AiSpend.month == month).first()
            if row is None:
                db.add(AiSpend(owner=owner, month=month, cost_usd=cost))
            else:
                row.cost_usd = (row.cost_usd or 0.0) + cost
            db.commit()
        finally:
            db.close()
        _forget(owner)
    except Exception as error:  # spend tracking must never break a chat
        logger.warning("AI spend tracking failed: %s", error)


def pause_reason(owner: Optional[str]) -> Optional[str]:
    """A message when the person's monthly cap is used up, else None (cached briefly)."""
    if not owner:
        return None
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(owner)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    try:
        info = status(owner)
        reason = None
        if info["paused"]:
            reason = (f"You've reached your monthly AI spending cap of ${info['cap_usd']:.2f}. "
                      "AI resumes on the 1st of next month, or raise the cap in Settings → Account → Your AI.")
    except Exception as error:
        logger.warning("AI budget check failed: %s", error)
        reason = None
    with _cache_lock:
        _cache[owner] = (now, reason)
    return reason
