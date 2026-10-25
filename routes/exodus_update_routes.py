"""Exodus one-click updates (admins). See src/exodus_updates.py."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core.middleware import require_admin
from src.auth_helpers import require_user
from src.exodus_updates import Updates, UpdateError


class ApproveBody(BaseModel):
    target: str = Field(..., min_length=40, max_length=40)


def setup_exodus_update_routes(updates: Updates | None = None):
    updates = updates or Updates()
    router = APIRouter(prefix="/api/updates")

    def admin(request: Request) -> str:
        user = require_user(request)
        require_admin(request)
        return user or "admin"

    @router.get("")
    async def view(request: Request):
        admin(request)
        return updates.view()

    @router.post("/check")
    async def check(request: Request):
        admin(request)
        try:
            return await updates.check(manual=True)
        except UpdateError as exc:
            raise HTTPException(429, str(exc)) from exc

    @router.post("/approve")
    async def approve(body: ApproveBody, request: Request):
        user = admin(request)
        try:
            return updates.approve(body.target, user)
        except UpdateError as exc:
            raise HTTPException(409, str(exc)) from exc

    router.updates = updates
    return router
