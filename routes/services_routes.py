# routes/services_routes.py
# Exodus Services manager (admin): turn the optional services on and off,
# remove them (data kept unless asked) and reinstall them. The app never talks
# to Docker itself; it forwards a fixed set of requests to the service manager
# helper (services/servicectl), which is an opt-in add-on
# (docker/service-manager.yml). Without it, the screen explains how to enable it.
import os
import re

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from core.middleware import require_admin

SERVICECTL_URL = os.environ.get("SERVICECTL_URL", "http://servicectl:8095")
TOKEN_PATH = os.environ.get("SERVICECTL_TOKEN_PATH", "/run/servicectl/token")
SERVICES = ("searxng", "chromadb", "ntfy", "vaultwarden", "harness", "replica")
ACTIONS = ("start", "stop", "remove", "reinstall")
ENABLE_HINT = (
    "The Services manager is an opt-in add-on because it needs access to Docker. "
    "To turn it on, add docker/service-manager.yml to COMPOSE_FILE in .env "
    "(COMPOSE_FILE=docker-compose.yml:docker-compose.override.yml:docker/service-manager.yml) "
    "and run `docker compose up -d` in the Exodus folder."
)


def _token():
    try:
        with open(TOKEN_PATH, encoding="utf-8") as handle:
            token = handle.read().strip()
        return token if len(token) >= 32 else None
    except OSError:
        return None


def _unavailable(reason):
    return {"available": False, "reason": reason, "hint": ENABLE_HINT, "services": []}


def setup_services_routes(client_factory=None) -> APIRouter:
    router = APIRouter(prefix="/api/services", tags=["services"])
    make_client = client_factory or (lambda: httpx.AsyncClient(base_url=SERVICECTL_URL, timeout=10))

    @router.get("")
    async def list_services(request: Request):
        require_admin(request)
        token = _token()
        if not token:
            return _unavailable("not_enabled")
        try:
            async with make_client() as client:
                response = await client.get("/services", headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError:
            return _unavailable("unreachable")
        if response.status_code != 200:
            return _unavailable("unreachable")
        services = [s for s in response.json().get("services", []) if s.get("name") in SERVICES]
        return {"available": True, "services": services}

    @router.post("/{name}/{action}")
    async def act(name: str, action: str, request: Request):
        require_admin(request)
        if name not in SERVICES or action not in ACTIONS or not re.fullmatch(r"[a-z]+", name):
            raise HTTPException(404, "Unknown service or action")
        token = _token()
        if not token:
            raise HTTPException(503, ENABLE_HINT)
        delete_data = False
        if action == "remove":
            try:
                body = await request.json()
            except ValueError:
                body = {}
            delete_data = isinstance(body, dict) and body.get("delete_data") is True
        try:
            async with make_client() as client:
                response = await client.post(
                    f"/services/{name}/{action}",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"delete_data": delete_data},
                )
        except httpx.HTTPError:
            raise HTTPException(503, "The service manager helper is not reachable.")
        if response.status_code == 409:
            raise HTTPException(409, "That service is already busy; try again when it finishes.")
        if response.status_code != 202:
            raise HTTPException(502, "The service manager helper refused the request.")
        return JSONResponse({"accepted": action, "service": name}, status_code=202)

    return router
