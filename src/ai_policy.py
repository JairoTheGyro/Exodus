"""Per-account AI opt-out, enforced at HTTP and shared inference boundaries."""
import asyncio
import re
from contextvars import ContextVar
from functools import wraps
from fastapi import HTTPException
from starlette.responses import JSONResponse
from src.home_store import ai_free

AI_OWNER = ContextVar('exodus_ai_owner', default=None)
_active = {}

def _track(owner, task):
    entries = _active.setdefault(owner, {})
    entries[task] = entries.get(task, 0) + 1

def _untrack(owner, task):
    entries = _active.get(owner, {})
    count = entries.get(task, 0)
    if count <= 1: entries.pop(task, None)
    else: entries[task] = count - 1
    if not entries: _active.pop(owner, None)



def require_ai(owner=None):
    owner = owner if owner is not None else AI_OWNER.get()
    if owner is not None and ai_free(owner):
        raise HTTPException(403, 'AI is disabled for this account. Change Workspace mode in Settings to use it.')


def tracked_ai(fn):
    """Keep asynchronous model operations cancellable when their owner opts out."""
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        require_ai()
        task = asyncio.current_task()
        owner = AI_OWNER.get()
        _track(owner, task)
        try:
            return await fn(*args, **kwargs)
        finally:
            _untrack(owner, task)
    return wrapped


def cancel_ai(owner):
    for task in tuple(_active.get(owner, ())):
        if task is not asyncio.current_task():
            task.cancel()


# Conservative, explicit non-AI surface. New API families are denied by default
# in this mode until reviewed. Existing data is retained; this is not deletion.
def allowed_without_ai(path, method):
    if not path.startswith('/api/'):
        return not path.startswith(('/v1/', '/ws', '/socket'))
    # Match complete route shapes, not open-ended content API prefixes.
    if path.startswith('/api/home/'):
        return True
    if path.startswith('/api/auth/'):
        return '/integrations' not in path or method == 'GET'
    if path.startswith(('/api/prefs', '/api/fonts', '/api/upstream', '/api/contacts/')):
        return True
    if path in ('/api/health', '/api/config', '/api/client-info', '/api/version'):
        return method == 'GET'
    if path in ('/api/notes/export/zip', '/api/notes/export/json'):
        return method == 'GET'
    if path == '/api/calendar/quick-parse':
        return method == 'POST'  # Local parser; optional inference has its own AI guard.
    if path == '/api/documents':
        return method == 'GET'
    if path == '/api/documents/upload':
        return method == 'POST'
    if re.fullmatch(r'/api/documents/[0-9a-f]{32}/download', path):
        return method == 'GET'
    if re.fullmatch(r'/api/documents/[0-9a-f]{32}', path) and method == 'DELETE':
        return True
    patterns = [
        r'/api/workshop/[^/]+/state',  # Saved tools run without generation/inference.
        r'/api/notes', r'/api/notes/reorder',
        r'/api/notes/[^/]+', r'/api/notes/[^/]+/(pin|archive)',
        r'/api/notes/[^/]+/items/[0-9]+/toggle',
        r'/api/calendar/(config|test|sync|calendars|events|import)',
        r'/api/calendar/config/accounts(?:/[^/]+)?',
        r'/api/calendar/(calendars|events|export)/[^/]+',
        r'/api/documents/(library|import-pdf|export-zip|tidy)',
        r'/api/activity/heartbeat',
        r'/api/document(?:/[^/]+)?',
        r'/api/document/[^/]+/(archive|extract-pdf-text|versions|render-pages|render-pdf|export-pdf|prepare-signed-reply)',
        r'/api/document/[^/]+/(version|restore)/[0-9]+',
        r'/api/document/[^/]+/page/[0-9]+\.png',
        r'/api/document/[^/]+/export-pdf/preview',
        r'/api/email/(list|unread-state|contacts|search|folders|scheduled|pending|resolve-contact|send|draft|schedule|config|accounts|compose-upload|compose-from-odysseus|compose-from-odysseus-zip)',
        r'/api/email/(read|attachments|attachments-download|inline-image|mark-unread|mark-read|flag|archive|delete|delete-permanent|move|mark-answered|clear-answered|scheduled|pending|compose-upload)/[^/]+',
        r'/api/email/(attachment|attachment-as-doc|attachment-path|compose-from-attachment)/[^/]+/[0-9]+',
        r'/api/email/accounts/[^/]+(?:/set-default)?',
        r'/api/email/oauth/google/(authorize|callback)',
        r'/api/email/[^/]+/unflag-spam',
    ]
    # These generic one-segment paths overlap named AI operations.
    if path in ('/api/notes/fire-reminder',):
        return False
    return any(re.fullmatch(pattern, path) for pattern in patterns)


class WorkspacePolicyMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] not in ('http', 'websocket'):
            return await self.app(scope, receive, send)
        state = scope.get('state', {})
        owner = state.get('api_token_owner') if state.get('api_token') else state.get('current_user')
        if owner is None:
            from src.owner_identity import auth_disabled
            if auth_disabled(): owner = ''
        if owner == 'internal-tool':
            owner = AI_OWNER.get()
        token = AI_OWNER.set(owner)
        path = scope.get('path', '')
        root = scope.get('root_path', '')
        if root and path.startswith(root):
            path = path[len(root):] or '/'
        try:
            if owner is not None and ai_free(owner) and not allowed_without_ai(path, scope.get('method', 'GET')):
                if scope['type'] == 'websocket':
                    await send({'type':'websocket.close', 'code':1008})
                else:
                    await JSONResponse({'detail':'AI features are disabled for this account.'}, status_code=403)(scope, receive, send)
                return
            await self.app(scope, receive, send)
        finally:
            AI_OWNER.reset(token)


def tracked_stream(fn):
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        require_ai()
        task, owner = asyncio.current_task(), AI_OWNER.get()
        _track(owner, task)
        stream = fn(*args, **kwargs)
        try:
            async for chunk in stream:
                require_ai()
                yield chunk
        finally:
            _untrack(owner, task)
            await stream.aclose()
    return wrapped


def scheduled_owner(fn):
    @wraps(fn)
    async def wrapped(self, task_id, *args, **kwargs):
        from core.database import SessionLocal, ScheduledTask
        with SessionLocal() as db:
            task = db.get(ScheduledTask, task_id)
            owner = task.owner if task else None
        token = AI_OWNER.set(owner)
        current = asyncio.current_task()
        _track(owner, current)
        try:
            return await fn(self, task_id, *args, **kwargs)
        finally:
            _untrack(owner, current)
            AI_OWNER.reset(token)
    return wrapped
