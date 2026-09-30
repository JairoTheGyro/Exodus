"""Scoped model gateway for the local Code service; provider secrets stay in Exodus."""
import hashlib
import json
import secrets
import threading
from pathlib import Path

from fastapi import HTTPException
from core.atomic_io import atomic_write_json
from src.constants import DATA_DIR

BRIDGE_DIR = Path(DATA_DIR) / 'code-bridge'
BRIDGE_FILE = BRIDGE_DIR / 'connection.json'
BRIDGE_PATHS = frozenset(('/api/code/bridge/v1/models', '/api/code/bridge/v1/chat/completions'))
_lock = threading.RLock()


def connection():
    try:
        value = json.loads(BRIDGE_FILE.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def connect(owner):
    with _lock:
        current = connection()
        if current and current.get('owner') != owner:
            raise HTTPException(409, 'Code is connected to another administrator. This workspace is single-user.')
        if not current:
            BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
            BRIDGE_DIR.chmod(0o700)
            current = {'owner': owner, 'token': 'exodus_code_' + secrets.token_urlsafe(48)}
            atomic_write_json(str(BRIDGE_FILE), current)
            BRIDGE_FILE.chmod(0o600)
        return current


def bridge_owner(request):
    """Validate only the model gateway's exact paths; never grant general app access."""
    from core.middleware import get_application_route_path
    if get_application_route_path(request.scope) not in BRIDGE_PATHS:
        return None
    stored = connection()
    token = stored.get('token')
    auth = request.headers.get('authorization', '')
    if not token or not secrets.compare_digest(auth, 'Bearer ' + token):
        return None
    owner = stored.get('owner')
    manager = getattr(request.app.state, 'auth_manager', None)
    if not owner or not manager or not manager.is_admin(owner):
        return None
    return owner


def model_id(endpoint, model):
    return 'exodus-' + hashlib.sha256(json.dumps([endpoint, model]).encode()).hexdigest()[:32]


def model_options(owner):
    from src.home_store import ai_free
    if ai_free(owner):
        return []
    from core.database import SessionLocal, ModelEndpoint
    from src.endpoint_resolver import _endpoint_enabled_models
    # Deliberately do not export other administrators' private connections.
    with SessionLocal() as db:
        endpoints = db.query(ModelEndpoint).filter(
            ModelEndpoint.is_enabled == True,
            (ModelEndpoint.owner == owner) | (ModelEndpoint.owner == None),
        ).all()
        result = []
        for ep in endpoints:
            if ep.model_type not in (None, 'llm') or ep.supports_tools is False:
                continue
            for model in _endpoint_enabled_models(ep):
                result.append({'id': model_id(ep.id, model), 'object': 'model', 'owned_by': 'exodus',
                               'name': f'{ep.name} / {model}', 'endpoint_id': ep.id, 'model': model})
        return result


async def openai_stream(source, model):
    """Translate Exodus's normalized provider stream, including native tool calls."""
    import time
    request_id = 'chatcmpl-' + secrets.token_hex(12)
    created = int(time.time())
    had_tools = False
    finished = False
    usage = None

    def chunk(delta, finish=None):
        return 'data: ' + json.dumps({'id': request_id, 'object': 'chat.completion.chunk',
            'created': created, 'model': model,
            'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}) + '\n\n'

    yield chunk({'role': 'assistant'})
    try:
        async for event in source:
            for frame in event.split('\n\n'):
                data = '\n'.join(line[6:] for line in frame.splitlines() if line.startswith('data: '))
                if not data:
                    continue
                if data == '[DONE]':
                    finished = True
                    continue
                value = json.loads(data)
                if 'event: error' in frame or value.get('type') == 'error':
                    yield 'data: ' + json.dumps({'error': {'message': 'The selected model request failed. Check its connection in Exodus.', 'type': 'upstream_error'}}) + '\n\n'
                    return
                if value.get('delta'):
                    yield chunk({'reasoning_content' if value.get('thinking') else 'content': value['delta']})
                if value.get('type') == 'tool_calls':
                    calls = value.get('calls', [])
                    had_tools = had_tools or bool(calls)
                    yield chunk({'tool_calls': [dict(index=i, id=c['id'], type='function',
                        function={'name': c['name'], 'arguments': c['arguments']}) for i, c in enumerate(calls)]})
                if value.get('type') == 'usage':
                    u = value.get('data', {})
                    usage = {'prompt_tokens': u.get('input_tokens', 0), 'completion_tokens': u.get('output_tokens', 0)}
                    usage['total_tokens'] = sum(usage.values())
        if not finished:
            yield 'data: ' + json.dumps({'error': {'message': 'The model stream ended before completion.', 'type': 'upstream_error'}}) + '\n\n'
            return
        yield chunk({}, 'tool_calls' if had_tools else 'stop')
        if usage is not None:
            yield 'data: ' + json.dumps({'id': request_id, 'object': 'chat.completion.chunk',
                'created': created, 'model': model, 'choices': [], 'usage': usage}) + '\n\n'
        yield 'data: [DONE]\n\n'
    except Exception:
        # Never forward provider exception text, which can contain keys or prompts.
        yield 'data: ' + json.dumps({'error': {'message': 'The model connection failed.', 'type': 'upstream_error'}}) + '\n\n'
    finally:
        await source.aclose()
