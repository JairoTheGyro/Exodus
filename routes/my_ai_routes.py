# routes/my_ai_routes.py
# Exodus "Your AI → My own cloud account": any signed-in person can connect
# their own AI provider account. It's private to them (ModelEndpoint.owner =
# them) and shows up only in their model picker.
#
# Safety: members never type a web address. They pick a provider from the
# fixed list below and paste their key, so a "connection" can't be pointed at
# Exodus's own internal services or the home network (the admin's Added
# Models screen, which allows local servers, stays admin-only).
import json
import re
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.auth_helpers import require_user

# key -> (name, base URL). Matches the providers offered by /setup.
PROVIDERS = {
    "openrouter": ("OpenRouter", "https://openrouter.ai/api/v1"),
    "openai": ("OpenAI", "https://api.openai.com/v1"),
    "anthropic": ("Anthropic", "https://api.anthropic.com/v1"),
    "gemini": ("Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai"),
    "deepseek": ("DeepSeek", "https://api.deepseek.com/v1"),
    "groq": ("Groq", "https://api.groq.com/openai/v1"),
    "xai": ("xAI", "https://api.x.ai/v1"),
    "nvidia": ("NVIDIA", "https://integrate.api.nvidia.com/v1"),
}
MAX_ACCOUNTS = 5
_KEY_RE = re.compile(r"^[\x21-\x7e]{8,512}$")  # printable, no spaces or line breaks


class AccountBody(BaseModel):
    provider: Optional[str] = None
    api_key: Optional[str] = None


def _provider_of(base_url: str) -> Optional[str]:
    for key, (_, url) in PROVIDERS.items():
        if (base_url or "").rstrip("/") == url:
            return key
    return None


def setup_my_ai_routes(probe=None) -> APIRouter:
    router = APIRouter(prefix="/api/my-ai", tags=["my-ai"])

    def _probe(base_url, api_key):
        if probe is not None:
            return probe(base_url, api_key)
        from routes.model_routes import _probe_endpoint
        return _probe_endpoint(base_url, api_key, timeout=10)

    def _who(request: Request) -> str:
        user = require_user(request) or None
        if not user:
            raise HTTPException(400, "Your own AI accounts need a sign-in account.")
        return user

    def _describe(ep) -> dict:
        try:
            models = json.loads(ep.cached_models or "[]")
        except ValueError:
            models = []
        key = _provider_of(ep.base_url)
        return {"id": ep.id, "name": ep.name, "provider": key,
                "provider_name": PROVIDERS[key][0] if key else None,
                "models": len(models), "enabled": bool(ep.is_enabled)}

    @router.get("/providers")
    def providers(request: Request):
        _who(request)
        return {"providers": [{"id": key, "name": name} for key, (name, _) in PROVIDERS.items()]}

    @router.get("/accounts")
    def accounts(request: Request):
        user = _who(request)
        from core.database import ModelEndpoint, SessionLocal
        db = SessionLocal()
        try:
            rows = db.query(ModelEndpoint).filter(ModelEndpoint.owner == user).all()
            return {"accounts": [_describe(ep) for ep in rows if _provider_of(ep.base_url)]}
        finally:
            db.close()

    @router.post("/accounts")
    def add_account(request: Request, body: AccountBody):
        user = _who(request)
        if body.provider not in PROVIDERS:
            raise HTTPException(400, "Choose a provider from the list.")
        key = (body.api_key or "").strip()
        if not _KEY_RE.fullmatch(key):
            raise HTTPException(400, "Paste the whole API key (no spaces).")
        name, base_url = PROVIDERS[body.provider]
        from core.database import ModelEndpoint, SessionLocal
        db = SessionLocal()
        try:
            mine = db.query(ModelEndpoint).filter(ModelEndpoint.owner == user).all()
            if sum(1 for ep in mine if _provider_of(ep.base_url)) >= MAX_ACCOUNTS:
                raise HTTPException(400, f"You can connect up to {MAX_ACCOUNTS} accounts.")
        finally:
            db.close()
        try:
            models = _probe(base_url, key) or []
        except Exception:
            models = []
        if not models:
            raise HTTPException(400, f"{name} didn't accept that key, or listed no models. Check the key and try again.")
        db = SessionLocal()
        try:
            ep = ModelEndpoint(
                id=str(uuid.uuid4()), name=f"{name} ({user})", base_url=base_url, api_key=key,
                is_enabled=True, model_type="llm", endpoint_kind="api",
                cached_models=json.dumps(models[:500]), owner=user,
            )
            db.add(ep)
            db.commit()
            return _describe(ep)
        finally:
            db.close()

    @router.delete("/accounts/{account_id}")
    def remove_account(request: Request, account_id: str):
        user = _who(request)
        from core.database import ModelEndpoint, SessionLocal
        db = SessionLocal()
        try:
            ep = db.query(ModelEndpoint).filter(ModelEndpoint.id == account_id, ModelEndpoint.owner == user).first()
            if ep is None or not _provider_of(ep.base_url):
                raise HTTPException(404, "Account not found.")
            db.delete(ep)
            db.commit()
            return {"ok": True}
        finally:
            db.close()

    return router
