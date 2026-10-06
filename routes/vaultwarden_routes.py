"""Authenticated companion status and separate-origin web-vault launch."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from src.auth_helpers import require_user
from src.vaultwarden_service import VaultwardenConfigError, VaultwardenService


_PRIVATE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def setup_vaultwarden_routes(service=None):
    service = service or VaultwardenService()
    router = APIRouter(tags=["vaultwarden"])

    def authorize(request):
        try:
            require_user(request)
        except HTTPException as exc:
            exc.headers = {**(exc.headers or {}), **_PRIVATE_HEADERS}
            raise

    def configuration_error():
        return HTTPException(
            503, "Vaultwarden connection settings are invalid. Ask the installation administrator to check them.",
            headers=_PRIVATE_HEADERS,
        )

    @router.get("/api/vaultwarden/config")
    async def config(request: Request):
        authorize(request)
        try:
            return JSONResponse(service.client_config(), headers=_PRIVATE_HEADERS)
        except VaultwardenConfigError:
            raise configuration_error() from None

    @router.get("/api/vaultwarden/status")
    async def status(request: Request):
        authorize(request)
        try:
            return JSONResponse(await service.status(), headers=_PRIVATE_HEADERS)
        except VaultwardenConfigError:
            raise configuration_error() from None

    @router.get("/vault/admin", include_in_schema=False)
    async def administration(request: Request):
        user = require_user(request)
        manager = getattr(request.app.state, "auth_manager", None)
        if not user or not manager or not manager.is_admin(user):
            raise HTTPException(403, "Admin only", headers=_PRIVATE_HEADERS)
        try:
            url = service.client_config()["vault_url"].rstrip("/") + "/admin"
        except VaultwardenConfigError:
            raise configuration_error() from None
        return RedirectResponse(url, status_code=303, headers=_PRIVATE_HEADERS)

    @router.get("/vault", include_in_schema=False)
    @router.get("/vault/", include_in_schema=False)
    async def launch(request: Request):
        authorize(request)
        try:
            public_url = service.client_config()["vault_url"]
        except VaultwardenConfigError:
            raise configuration_error() from None
        # Preserve Vaultwarden's independent origin and sign-in. No Exodus
        # cookie, bearer token, or secret is appended to the destination URL.
        return RedirectResponse(public_url, status_code=303, headers=_PRIVATE_HEADERS)

    return router
