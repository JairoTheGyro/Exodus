"""Workshop generation and isolated state; source lives in existing Documents."""
import asyncio
import hashlib
import json
import threading
from pathlib import Path
from typing import Optional, Literal

import httpx

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core.atomic_io import atomic_write_json
from core.database import Document, ModelEndpoint, SessionLocal
from core.middleware import require_admin
from routes.document_helpers import _verify_doc_owner
from src.auth_helpers import owner_filter, require_privilege
from src.constants import WORKSHOP_STATE_DIR
from src.workshop import (
    MARKER, MAX_SOURCE_BYTES, MAX_STATE_BYTES, WorkshopBrief,
    assess_brief, build_messages, normalize_workshop_source,
)

_state_lock = threading.RLock()
_build_lock = asyncio.Lock()


class BuildRequest(WorkshopBrief):
    engine: Literal["harness", "direct"] = "harness"
    endpoint_id: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=300)
    acknowledged: bool = False
    document_id: Optional[str] = Field(default=None, max_length=100)


class StateUpdate(BaseModel):
    revision: int = Field(ge=0)
    data: dict


def _document(request, doc_id):
    user = require_privilege(request, "can_use_documents")
    with SessionLocal() as db:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            raise HTTPException(404, "App not found")
        _verify_doc_owner(db, doc, user or None)
        if not (doc.current_content or "").lstrip().startswith(MARKER):
            raise HTTPException(400, "This document is not a Workshop app")
        return {"content": doc.current_content, "version": doc.version_count}


def _state_path(doc_id):
    # Never interpret an incoming document identifier as a filesystem path.
    name = hashlib.sha256(doc_id.encode("utf-8")).hexdigest() + ".json"
    return Path(WORKSHOP_STATE_DIR) / name


def _read_state(doc_id):
    path = _state_path(doc_id)
    if not path.exists():
        return {"revision": 0, "data": {}}
    try:
        if path.stat().st_size > MAX_STATE_BYTES + 1000:
            raise ValueError("State too large")
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or not isinstance(state.get("data"), dict):
            raise ValueError("Invalid state")
        if type(state.get("revision")) is not int or state["revision"] < 0:
            raise ValueError("Invalid revision")
        return state
    except (OSError, ValueError) as exc:
        raise HTTPException(409, "Saved app data could not be read. It has not been overwritten.") from exc


def _model_options(request):
    from routes.model_routes import _picker_models_for_endpoint
    from routes.chat_helpers import _allowed_models_for_request
    user = require_privilege(request, "can_use_documents")
    allowed = _allowed_models_for_request(request)
    with SessionLocal() as db:
        query = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True)
        if user:
            query = owner_filter(query, ModelEndpoint, user)
        result = []
        for ep in query.all():
            if ep.model_type not in (None, "llm"):
                continue
            models, _ = _picker_models_for_endpoint(ep, ep.base_url, ep.endpoint_kind or "auto")
            for model in models:
                if allowed is not None and model not in allowed:
                    continue
                result.append({
                    "endpoint_id": ep.id, "model": model,
                    "label": f"{ep.name} / {model}",
                })
        return result


def setup_workshop_routes():
    router = APIRouter(prefix="/api/workshop", tags=["workshop"])

    @router.post("/assess")
    def assess(request: Request, brief: WorkshopBrief):
        require_privilege(request, "can_use_documents")
        return assess_brief(brief)

    @router.get("/models")
    def models(request: Request):
        options = _model_options(request)
        try:
            require_admin(request)
            can_generate = True
        except HTTPException:
            can_generate = False
        from src.harness_bridge import model_options
        coding = {(m['endpoint_id'], m['model']) for m in model_options(require_privilege(request, "can_use_documents"))} if can_generate else set()
        for option in options:
            option['harness_compatible'] = (option['endpoint_id'], option['model']) in coding
        return {"models": options, "can_generate": can_generate}

    @router.post("/generate")
    async def generate(request: Request, body: BuildRequest):
        # This initial Workshop is an administrator-operated builder. Saved
        # apps remain owner-scoped. No new delegated model-spend capability.
        require_admin(request)
        user = require_privilege(request, "can_use_documents")
        brief = WorkshopBrief(**body.model_dump())
        assessment = assess_brief(brief)
        if not assessment["can_build"]:
            raise HTTPException(422, assessment["message"])
        if assessment["zone"] == "yellow" and not body.acknowledged:
            raise HTTPException(409, "Acknowledge the local-prototype limits before building.")
        if not any(m["endpoint_id"] == body.endpoint_id and m["model"] == body.model for m in _model_options(request)):
            raise HTTPException(400, "Choose a connected model available to your account.")
        previous = _document(request, body.document_id) if body.document_id else None
        if previous and len(previous["content"].encode("utf-8")) > MAX_SOURCE_BYTES:
            raise HTTPException(413, "This app is too large to revise in the lightweight Workshop.")
        if _build_lock.locked():
            raise HTTPException(429, "Another Workshop build is running. Try again when it finishes.")
        from src.endpoint_resolver import resolve_endpoint_by_id
        from src.llm_core import llm_call_async
        async with _build_lock:
            route = resolve_endpoint_by_id(body.endpoint_id, body.model, owner=user or None, require_exact_model=True)
            if not route:
                raise HTTPException(400, "That model connection is no longer available. Check Settings.")
            url, model, headers = route
            if body.engine == 'harness':
                from routes.code_routes import admin_owner
                from src.harness_bridge import connect, model_options
                owner = admin_owner(request)
                selected = next((m for m in model_options(owner) if m['endpoint_id'] == body.endpoint_id and m['model'] == body.model), None)
                if not selected:
                    raise HTTPException(400, "Harness needs a connected model that supports coding tools. Check Model settings or use the basic builder in Advanced options.")
                current = connect(owner)
                messages = build_messages(brief, previous["content"] if previous else "")
                instructions = messages[0]['content'].replace(
                    'Return ONLY a complete HTML document, from <!doctype html> through </html>, with',
                    'Build a complete HTML document, from <!doctype html> through </html>, with')
                instructions += "\nUse submit_workshop_app to submit the complete source. Read its checks, fix any issues, and resubmit. Finish after an accepted submission. Checks are basic, not a safety audit. No shell, browsing, packages, or filesystem tools are available."
                async def run():
                    try:
                        async with httpx.AsyncClient(timeout=httpx.Timeout(310, connect=5), trust_env=False) as client:
                            response = await client.post('http://harness:3081/workshop/build',
                                headers={'Authorization': 'Bearer ' + current['token']},
                                json={'model': selected['id'], 'instructions': instructions, 'prompt': messages[1]['content']})
                            if response.status_code == 429:
                                raise HTTPException(429, "Another Workshop build is running. Try again when it finishes.")
                            if response.status_code != 200:
                                raise HTTPException(502, "Harness could not complete this build. Check Code and your model connection, or try a smaller brief. Nothing was saved.")
                            result = response.json()
                            return result['source']
                    except httpx.ConnectError as exc:
                        raise HTTPException(503, "The coding engine is unavailable. Start Harness in Docker and try again, or choose the basic builder in Advanced options.") from exc
                    except httpx.TimeoutException as exc:
                        raise HTTPException(504, "The coding engine timed out. Nothing was saved. Try a smaller brief.") from exc
                    except (httpx.HTTPError, ValueError, KeyError) as exc:
                        raise HTTPException(502, "The coding engine could not return a complete app. Nothing was saved.") from exc
                task = asyncio.create_task(run())
                try:
                    while not task.done():
                        await asyncio.wait({task}, timeout=0.5)
                        if await request.is_disconnected():
                            raise HTTPException(499, "Build cancelled. Nothing was saved.")
                    raw = await task
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
            else:
                try:
                    raw = await asyncio.wait_for(llm_call_async(
                        url, model, build_messages(brief, previous["content"] if previous else ""),
                        headers=headers, temperature=0.3, max_tokens=12000,
                        timeout=180, max_retries=0, prompt_type="workshop",
                    ), timeout=190)
                except (asyncio.TimeoutError, TimeoutError) as exc:
                    raise HTTPException(504, "The model timed out. Try a smaller brief; nothing was saved.") from exc
                except Exception as exc:
                    # Provider exceptions can contain credentials or echoed prompts.
                    raise HTTPException(502, "The model could not finish this build. Check its connection and try again.") from exc
            try:
                source = normalize_workshop_source(raw)
            except (ValueError, AttributeError) as exc:
                raise HTTPException(422, "The model did not return a complete, small HTML app. Try a smaller brief; nothing was saved.") from exc
        return {
            "title": brief.title.strip(), "content": source, "language": "html", "engine": body.engine,
            "document_id": body.document_id,
            "base_version": previous["version"] if previous else None,
            "assessment": assessment,
        }

    @router.get("/{doc_id}/state")
    def get_state(request: Request, doc_id: str):
        _document(request, doc_id)
        with _state_lock:
            return _read_state(doc_id)

    @router.put("/{doc_id}/state")
    def put_state(request: Request, doc_id: str, body: StateUpdate):
        _document(request, doc_id)
        try:
            size = len(json.dumps(body.data, allow_nan=False).encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, "App data must be a JSON object.") from exc
        if size > MAX_STATE_BYTES:
            raise HTTPException(413, "App data exceeds the 100 KB prototype limit. Export it before reducing its size.")
        with _state_lock:
            current = _read_state(doc_id)
            if current["revision"] != body.revision:
                raise HTTPException(409, "This app's data changed in another window. Reopen it before saving again.")
            result = {"revision": current["revision"] + 1, "data": body.data}
            path = _state_path(doc_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(str(path), result)
            return result

    return router
