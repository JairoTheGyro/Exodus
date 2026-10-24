# routes/ai_budget_routes.py
# Exodus "Your AI" (src/ai_budget.py): each person chooses shared AI, their own
# cloud account, or no AI, and can set a monthly spending cap. Admins can set a
# cap per member that the member can't raise. Choosing "No AI" turns on the
# existing per-account AI-free workspace mode; any other choice turns it off.
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src import ai_budget
from src.auth_helpers import require_user


class ChoiceBody(BaseModel):
    source: Optional[str] = None
    self_cap_usd: Optional[float] = None
    clear_cap: bool = False


class AdminCapBody(BaseModel):
    admin_cap_usd: Optional[float] = None


def _set_mode(owner: str, mode: str) -> None:
    from src.home_store import database, profile, save
    from src.ai_policy import cancel_ai
    with database() as conn:
        value = profile(owner, conn)
        if value.get("mode") == mode:
            return
        value["mode"] = mode
        save(owner, value, conn)
    if mode == "ai-free":
        cancel_ai(owner)
    else:
        try:
            from src.note_indexing import reindex_owner_notes
            reindex_owner_notes(owner)
        except Exception:
            pass


def _connections(owner: str) -> dict:
    """Names of the AI connections this person can use (no keys or addresses)."""
    from core.database import ModelEndpoint, SessionLocal
    db = SessionLocal()
    try:
        rows = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True).all()  # noqa: E712
        llm = [r for r in rows if (r.model_type or "llm") == "llm"]
        return {
            "own": sorted(r.name for r in llm if r.owner == owner),
            "shared": sorted(r.name for r in llm if r.owner is None),
        }
    finally:
        db.close()


def setup_ai_budget_routes() -> APIRouter:
    router = APIRouter(prefix="/api/ai-budget", tags=["ai-budget"])

    def _who(request: Request):
        user = require_user(request) or None
        if not user:
            raise HTTPException(400, "Choosing your AI needs a sign-in account.")
        auth = getattr(request.app.state, "auth_manager", None)
        try:
            is_admin = bool(auth and auth.is_admin(user))
        except Exception:
            is_admin = False
        return user, is_admin, auth

    def _view(user, is_admin):
        from src.home_store import ai_free
        info = ai_budget.status(user)
        return {**info, "me": user, "is_admin": is_admin, "ai_free": bool(ai_free(user)),
                "connections": _connections(user)}

    @router.get("")
    def get_choice(request: Request):
        user, is_admin, _ = _who(request)
        return _view(user, is_admin)

    @router.put("")
    def save_choice(request: Request, body: ChoiceBody):
        user, is_admin, _ = _who(request)
        cap = None if body.clear_cap else (body.self_cap_usd if body.self_cap_usd is not None else "__keep__")
        try:
            ai_budget.save_choice(user, source=body.source, self_cap_usd=cap)
        except ai_budget.BudgetError as error:
            raise HTTPException(400, str(error))
        if body.source == "off":
            _set_mode(user, "ai-free")
        elif body.source in ("shared", "own"):
            _set_mode(user, "full")
        return _view(user, is_admin)

    @router.get("/members")
    def members(request: Request):
        user, is_admin, auth = _who(request)
        if not is_admin:
            raise HTTPException(403, "Only admins can see everyone's AI spending.")
        names = sorted(getattr(auth, "users", {}) or {})
        return {"members": [{"username": name, **ai_budget.status(name)} for name in names]}

    @router.put("/members/{username}")
    def set_member_cap(request: Request, username: str, body: AdminCapBody):
        user, is_admin, auth = _who(request)
        if not is_admin:
            raise HTTPException(403, "Only admins can set someone's AI cap.")
        if username not in (getattr(auth, "users", {}) or {}):
            raise HTTPException(404, "There is no account with that username.")
        try:
            return {"username": username, **ai_budget.set_admin_cap(username, body.admin_cap_usd)}
        except ai_budget.BudgetError as error:
            raise HTTPException(400, str(error))

    return router
