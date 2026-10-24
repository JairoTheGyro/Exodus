# routes/space_routes.py
# Exodus shared spaces API (src/spaces.py). Every signed-in account can create
# a space and manage the ones it manages; workspace admins can manage all.
# Spaces need accounts, so single-user mode (no sign-in) answers 400.
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src import spaces
from src.auth_helpers import require_user


class SpaceBody(BaseModel):
    name: Optional[str] = None


class MemberBody(BaseModel):
    username: Optional[str] = None
    role: Optional[str] = "member"


def setup_space_routes() -> APIRouter:
    router = APIRouter(prefix="/api/spaces", tags=["spaces"])

    def _who(request: Request):
        user = require_user(request) or None
        if not user:
            raise HTTPException(400, "Shared spaces need sign-in accounts.")
        auth = getattr(request.app.state, "auth_manager", None)
        try:
            is_admin = bool(auth and auth.is_admin(user))
        except Exception:
            is_admin = False
        return user, is_admin, auth

    def _run(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except spaces.SpaceError as error:
            raise HTTPException(error.status, str(error))

    @router.get("")
    def list_spaces(request: Request):
        user, is_admin, _ = _who(request)
        return {"me": user, "spaces": spaces.list_spaces(user, is_admin)}

    @router.post("")
    def create_space(request: Request, body: SpaceBody):
        user, _, _ = _who(request)
        return _run(spaces.create_space, user, body.name)

    @router.put("/{space_id}")
    def rename_space(request: Request, space_id: str, body: SpaceBody):
        user, is_admin, _ = _who(request)
        return _run(spaces.rename_space, user, space_id, body.name, is_admin=is_admin)

    @router.delete("/{space_id}")
    def delete_space(request: Request, space_id: str):
        user, is_admin, _ = _who(request)
        _run(spaces.delete_space, user, space_id, is_admin=is_admin)
        return {"ok": True}

    @router.post("/{space_id}/members")
    def add_member(request: Request, space_id: str, body: MemberBody):
        user, is_admin, auth = _who(request)
        known = set(getattr(auth, "users", {}) or {}) if auth else set()
        return _run(spaces.add_member, user, space_id, body.username, known,
                    is_admin=is_admin, role=body.role or "member")

    @router.delete("/{space_id}/members/{username}")
    def remove_member(request: Request, space_id: str, username: str):
        user, is_admin, _ = _who(request)
        _run(spaces.remove_member, user, space_id, username, is_admin=is_admin)
        return {"ok": True}

    return router
