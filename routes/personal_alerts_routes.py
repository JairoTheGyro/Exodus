# routes/personal_alerts_routes.py
# Exodus private phone alerts (src/personal_alerts.py): each signed-in person
# sees their own ntfy topic, can send themselves a test and can get a new
# topic. Single-user installs show the shared installation topic instead.
import os

from fastapi import APIRouter, HTTPException, Request

from src.auth_helpers import require_user


def setup_personal_alerts_routes() -> APIRouter:
    router = APIRouter(prefix="/api/alerts/phone", tags=["alerts"])

    def _status(user):
        from src.personal_alerts import personal_topic, public_server_url
        enabled = os.getenv("NTFY_ENABLED", "true").lower() in ("true", "1", "yes")
        server = public_server_url()
        mine = personal_topic(user)
        topic = mine or os.getenv("NTFY_DEFAULT_TOPIC", "exodus-alerts")
        return {
            "enabled": enabled,
            "personal": bool(mine),
            "server": server,
            "topic": topic,
            "subscribe_url": f"{server}/{topic}",
        }

    @router.get("")
    def get_status(request: Request):
        return _status(require_user(request) or None)

    @router.post("/test")
    async def send_test(request: Request):
        user = require_user(request) or None
        from src.notifications import dispatch_notification
        result = await dispatch_notification(
            "This is a test from Exodus. Your phone alerts work.",
            title="Exodus test", priority=3, tags=["white_check_mark"], owner=user)
        return result

    @router.post("/reset")
    def reset(request: Request):
        user = require_user(request) or None
        from src.personal_alerts import personal_topic, reset_topic
        if not personal_topic(user):
            raise HTTPException(400, "Private alert addresses need sign-in accounts.")
        reset_topic(user)
        return _status(user)

    return router
