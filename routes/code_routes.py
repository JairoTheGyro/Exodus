"""Code launcher and narrowly authenticated, OpenAI-compatible model gateway."""
import asyncio
import json

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from core.middleware import require_admin
from src.auth_helpers import get_current_user
from src.harness_bridge import connection, connect, bridge_owner, model_options, openai_stream

MAX_BODY = 4_000_000


def admin_owner(request):
    require_admin(request)
    owner = get_current_user(request)
    manager = getattr(request.app.state, 'auth_manager', None)
    if not owner or not manager or not manager.is_admin(owner):
        raise HTTPException(403, 'Sign in with your administrator account to use Code.')
    current = connection()
    if current and current.get('owner') != owner:
        raise HTTPException(403, 'This local Code workspace belongs to another administrator.')
    return owner


def gateway_owner(request):
    owner = bridge_owner(request)
    if not owner:
        raise HTTPException(401, 'Invalid Code model connection')
    return owner


def setup_code_routes():
    router = APIRouter(prefix='/api/code', tags=['code'])

    @router.get('/status')
    async def status(request: Request):
        owner = admin_owner(request)
        running = False
        launch_url = None
        synced_count = 0
        current = connection()
        try:
            if current.get('token'):
                async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
                    r = await client.get('http://harness:3081/status', headers={
                        'Authorization': 'Bearer ' + current['token']})
                    state = r.json() if r.status_code == 200 else {}
                    token = state.get('launch_token')
                    import re
                    if state.get('ready') and isinstance(token, str) and re.fullmatch(r'[A-Za-z0-9_-]{20,200}', token):
                        running = True
                        launch_url = 'http://localhost:8093/?token=' + token
                        synced_count = state.get('model_count', 0)
        except (httpx.HTTPError, ValueError):
            pass
        return JSONResponse({'running': running, 'connected': current.get('owner') == owner,
                'launch_url': launch_url, 'synced_count': synced_count,
                'models': [{'id': m['id'], 'name': m['name']} for m in model_options(owner)]},
                headers={'Cache-Control': 'no-store'})

    @router.post('/connect')
    def connect_models(request: Request):
        owner = admin_owner(request)
        connect(owner)
        return {'connected': True}

    @router.get('/bridge/v1/models')
    def models(request: Request):
        owner = gateway_owner(request)
        return {'object': 'list', 'data': [
            {k: v for k, v in m.items() if k not in ('endpoint_id', 'model')}
            for m in model_options(owner)]}

    @router.post('/bridge/v1/chat/completions')
    async def completions(request: Request):
        owner = gateway_owner(request)
        raw = bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw) > MAX_BODY:
                raise HTTPException(413, 'Code request exceeds 4 MB')
        try:
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            raise HTTPException(400, 'Expected a JSON request')
        if body.get('stream') is not True:
            raise HTTPException(400, 'This coding gateway requires stream=true')
        selected = next((m for m in model_options(owner) if m['id'] == body.get('model')), None)
        if not selected:
            raise HTTPException(404, 'This model is unavailable or disabled in Exodus. Connect a tool-capable model in Settings.')
        messages, tools = body.get('messages'), body.get('tools')
        if not isinstance(messages, list) or not messages or len(messages) > 2000 or any(
            not isinstance(m, dict) or m.get('role') not in ('system', 'developer', 'user', 'assistant', 'tool') for m in messages):
            raise HTTPException(400, 'Invalid chat messages')
        if tools is not None and (not isinstance(tools, list) or len(tools) > 128 or any(
            not isinstance(t, dict) or t.get('type') != 'function' or not isinstance(t.get('function'), dict) for t in tools)):
            raise HTTPException(400, 'Invalid function tools')
        try:
            temperature = float(body.get('temperature', 0.3))
            maximum = int(body.get('max_tokens', body.get('max_completion_tokens', 4096)))
            if not 0 <= temperature <= 2 or not 1 <= maximum <= 65536:
                raise ValueError()
        except (TypeError, ValueError):
            raise HTTPException(400, 'Invalid generation limits')
        from src.endpoint_resolver import resolve_endpoint_by_id
        from src.llm_core import stream_llm
        route = resolve_endpoint_by_id(selected['endpoint_id'], selected['model'], owner=owner, require_exact_model=True)
        if not route:
            raise HTTPException(503, 'The selected Exodus model connection is unavailable')
        url, model, headers = route
        messages = [dict(m, role='system') if m['role'] == 'developer' else m for m in messages]

        async def generate():
            async with asyncio.timeout(600):
                source = stream_llm(url, model, messages, headers=headers, temperature=temperature,
                    max_tokens=maximum, tools=tools, tool_choice_none=body.get('tool_choice') == 'none',
                    timeout=300, prompt_type='code')
                async for event in openai_stream(source, selected['id']):
                    yield event
        return StreamingResponse(generate(), media_type='text/event-stream',
            headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})

    return router
