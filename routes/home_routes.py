"""Non-AI Home: owner-scoped views over existing content and real personal state."""
import json
import logging
import re
import time
import uuid
from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit
import httpx
from sqlalchemy.exc import SQLAlchemyError
from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from core.database import SessionLocal, Note, Document, DocumentFile
from src.auth_helpers import require_user, require_privilege
from src.home_store import database, profile, save
from src.ai_policy import cancel_ai

_weather_cache = {}
logger = logging.getLogger(__name__)

WIDGETS = ['tasks', 'schedule', 'focus', 'inbox', 'files', 'capture', 'apps', 'metrics', 'team', 'weather']

class Preferences(BaseModel):
    mode: Literal['full', 'ai-free'] | None = None
    role: Literal['personal', 'developer', 'sales', 'team'] | None = None
    order: list[str] | None = Field(default=None, max_length=10)
    hidden: list[str] | None = Field(default=None, max_length=10)
    collapsed: list[str] | None = Field(default=None, max_length=10)
    status: Literal['available', 'focus', 'meeting', 'lunch', 'away'] | None = None
    share_presence: bool | None = None
    pins: list[str] | None = Field(default=None, max_length=40)
    city: str | None = Field(default=None, max_length=100)
    weather_enabled: bool | None = None
    ai_include_archived_notes: bool | None = None

class TaskCreate(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    project: str = Field(default='', max_length=100)
    due: date | None = None
    priority: Literal['normal', 'high'] = 'normal'

class Toggle(BaseModel):
    text: str = Field(max_length=5000)
    done: bool

class Capture(BaseModel):
    text: str = Field(min_length=1, max_length=20000)

class ScratchpadSave(BaseModel):
    text: str = Field(max_length=20000)
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')

class ScratchpadNote(BaseModel):
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    request_id: uuid.UUID

class Timer(BaseModel):
    action: Literal['start', 'stop']
    project: str = Field(default='Focus', max_length=100)
    minutes: int = Field(default=25, ge=1, le=180)
    kind: Literal['pomodoro', 'timer'] = 'pomodoro'

class Announcement(BaseModel):
    body: str = Field(min_length=1, max_length=2000)

class Goal(BaseModel):
    id: str | None = Field(default=None, max_length=40)
    title: str = Field(min_length=1, max_length=80)
    current: float = Field(ge=0, le=1e12, allow_inf_nan=False)
    target: float = Field(gt=0, le=1e12, allow_inf_nan=False)

class Shortcut(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=1, max_length=2000)


def task_rows(owner, db):
    rows = []
    notes = db.query(Note).filter(Note.owner == (owner or None), Note.archived == False, Note.note_type == 'checklist').order_by(Note.updated_at.desc()).limit(500).all()
    for note in notes:
        try: items = json.loads(note.items or '[]')
        except ValueError: continue
        if not isinstance(items, list): continue
        for index, item in enumerate(items):
            if not isinstance(item, dict): continue
            rows.append({'note_id': note.id, 'index': index, 'text': str(item.get('text', '')),
                         'done': bool(item.get('done')), 'due': item.get('due') or note.due_date,
                         'priority': item.get('priority', 'normal'), 'project': note.label or note.title or 'Checklist'})
    return rows


def home_document_title(doc):
    """Resolve an email draft's envelope subject without parsing quoted mail."""
    if doc.language != 'email':
        return doc.title
    header, separator, _ = (doc.current_content or '').replace('\r\n', '\n').partition('\n---\n')
    if separator:
        # Match the editor's envelope, including folded header values. Limit
        # scanning to the header: a Subject: in the quoted body is not ours.
        header = re.sub(r'\n[ \t]+', ' ', header)
        match = re.search(r'^Subject:[ \t]*(.*)$', header, re.I | re.M)
        return (match.group(1).strip() if match else '') or '(No Subject)'
    title = (doc.title or '').strip()
    return title if title.lower() not in ('', 'email', 'new email', 'new mail', 'new message') else '(No Subject)'


def setup_home_routes():
    router = APIRouter(prefix='/api/home', tags=['home'])

    @router.get('/profile')
    def get_profile(request: Request):
        owner = require_user(request)
        return {'owner': owner, 'profile': profile(owner), 'widgets': WIDGETS}

    @router.patch('/profile')
    async def update_profile(request: Request, body: Preferences):
        owner = require_user(request)
        patch = body.model_dump(exclude_none=True)
        for key in ('order', 'hidden', 'collapsed'):
            if key in patch and (len(set(patch[key])) != len(patch[key]) or not set(patch[key]) <= set(WIDGETS)):
                raise HTTPException(422, 'Unknown or duplicate widget')
        with database() as conn:
            value = profile(owner, conn)
            value.update(patch)
            save(owner, value, conn)
        if body.mode == 'ai-free': cancel_ai(owner)
        if body.mode == 'full' or body.ai_include_archived_notes is not None:
            from src.note_indexing import reindex_owner_notes
            # Reuses the queue; AI-free accounts only enqueue consent cleanup.
            # Failure cannot undo a saved privacy choice; retrieval reads it live.
            try:
                reindex_owner_notes(owner)
            except Exception:
                logger.warning('Memory policy saved; note indexing will resume on the next save')
        return {'profile': value}

    @router.get('/tasks')
    def tasks(request: Request):
        owner = require_user(request)
        with SessionLocal() as db:
            return {'tasks': task_rows(owner, db), 'limit_notes': 500}

    @router.post('/tasks')
    def create_task(request: Request, body: TaskCreate):
        owner = require_user(request)
        if not body.text.strip(): raise HTTPException(422, 'Enter a task')
        with SessionLocal() as db:
            note = Note(id=str(uuid.uuid4()), owner=owner or None, title=body.text.strip(),
                        label=body.project.strip() or None, note_type='checklist', source='user',
                        due_date=body.due.isoformat() if body.due else None,
                        items=json.dumps([{'text': body.text.strip(), 'done': False, 'priority': body.priority}]))
            db.add(note); db.commit()
            return {'note_id': note.id}

    @router.put('/tasks/{note_id}/{index}')
    def toggle(request: Request, note_id: str, index: int, body: Toggle):
        owner = require_user(request)
        with SessionLocal() as db:
            note = db.query(Note).filter(Note.id == note_id, Note.owner == (owner or None)).first()
            if not note or note.note_type != 'checklist': raise HTTPException(404, 'Task not found')
            items = json.loads(note.items or '[]')
            if index < 0 or index >= len(items) or items[index].get('text') != body.text:
                raise HTTPException(409, 'This checklist changed. Refresh before updating it.')
            items[index]['done'] = body.done
            note.items = json.dumps(items); db.commit()
            return {'done': body.done}

    @router.post('/capture')
    def capture(request: Request, body: Capture):
        owner = require_user(request)
        if not body.text.strip(): raise HTTPException(422, 'Write a note first')
        with SessionLocal() as db:
            note = Note(id=str(uuid.uuid4()), owner=owner or None, title=body.text.splitlines()[0][:100], content=body.text, note_type='note', source='user')
            db.add(note); db.commit()
            return {'id': note.id}

    @router.get('/scratchpad')
    def get_scratchpad(request: Request):
        return scratchpad_response(request, 'read')

    @router.put('/scratchpad')
    def save_scratchpad(request: Request, body: ScratchpadSave):
        return scratchpad_response(request, 'write', body)

    @router.post('/scratchpad/to-note')
    def save_scratchpad_note(request: Request, body: ScratchpadNote):
        return scratchpad_response(request, 'to_note', body)

    def scratchpad_response(request, action, body=None):
        from src.scratchpad import ScratchpadStore, ScratchpadConflict, ScratchpadEmpty, ScratchpadDeleted
        from src.workspace_events import publish_workspace_event
        owner = require_user(request)
        headers = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
        try:
            store = ScratchpadStore()
            if action == 'read':
                result = store.read(owner)
            elif action == 'write':
                result = store.write(owner, body.text, body.revision)
            else:
                result = store.to_note(owner, body.revision, body.request_id, SessionLocal, Note)
            if action != 'read':
                publish_workspace_event(owner, 'scratchpad')
            return JSONResponse(result, headers=headers)
        except ScratchpadConflict as exc:
            raise HTTPException(409, {'message': exc.message, 'current': exc.current}, headers=headers) from None
        except ScratchpadDeleted as exc:
            raise HTTPException(410, str(exc), headers=headers) from None
        except ScratchpadEmpty as exc:
            raise HTTPException(422, str(exc), headers=headers) from None
        except (OSError, ValueError, SQLAlchemyError):
            raise HTTPException(503, 'Scratchpad storage is unavailable. Your text has not been discarded.', headers=headers) from None

    @router.get('/diagnostics')
    async def system_diagnostics(request: Request):
        from src.home_diagnostics import diagnostics
        require_user(request)
        return JSONResponse(await diagnostics(), headers={'Cache-Control': 'no-store'})

    @router.get('/files')
    def files(request: Request):
        owner = require_privilege(request, 'can_use_documents')
        pins = profile(owner).get('pins', [])
        with SessionLocal() as db:
            query = db.query(Document).filter(Document.owner == (owner or None), Document.archived == False, Document.is_active == True)
            documents = query.order_by(Document.updated_at.desc()).limit(12).all()
            pinned = query.filter(Document.id.in_(pins)).all() if pins else []
            rows = [{'id': row.id, 'source_id': row.id, 'kind': 'document',
                     'title': home_document_title(row), 'language': row.language,
                     'updated': row.updated_at.isoformat()+'Z', 'pinned': row.id in pins}
                    for row in {item.id: item for item in pinned + documents}.values()]
            for model, kind, prefix in ((DocumentFile, 'upload', 'upload:'), (Note, 'note', 'note:')):
                query = db.query(model).filter(model.owner == (owner or None))
                query = query.filter(model.deletion_pending == False) if kind == 'upload' else query.filter(model.archived == False)
                records = query.order_by(model.updated_at.desc()).limit(12).all()
                ids = [value[len(prefix):] for value in pins if value.startswith(prefix)]
                pinned = query.filter(model.id.in_(ids)).all() if ids else []
                for row in {item.id: item for item in pinned + records}.values():
                    item_id = prefix + row.id
                    rows.append({'id': item_id, 'source_id': row.id, 'kind': kind,
                                 'title': row.filename if kind == 'upload' else (row.title or 'Untitled note'),
                                 'language': 'file' if kind == 'upload' else row.note_type,
                                 'updated': row.updated_at.isoformat()+'Z', 'pinned': item_id in pins})
            rows.sort(key=lambda row: row['updated'], reverse=True)
            return {'files': [row for index, row in enumerate(rows) if index < 12 or row['pinned']]}

    @router.get('/search')
    def search(request: Request, q: str = Query(min_length=2, max_length=200)):
        owner = require_user(request)
        needle = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        results = []
        with SessionLocal() as db:
            try: require_privilege(request, 'can_use_documents'); docs_allowed = True
            except HTTPException: docs_allowed = False
            if docs_allowed:
                for doc in db.query(Document).filter(Document.owner == (owner or None), Document.archived == False, Document.is_active == True,
                    (Document.title.ilike(needle, escape='\\')) | (Document.current_content.ilike(needle, escape='\\'))).limit(15):
                    results.append({'kind': 'file', 'id': doc.id, 'title': doc.title})
            for note in db.query(Note).filter(Note.owner == (owner or None), Note.archived == False,
                (Note.title.ilike(needle, escape='\\')) | (Note.content.ilike(needle, escape='\\')) | (Note.items.ilike(needle, escape='\\'))).limit(15):
                results.append({'kind': 'task' if note.note_type == 'checklist' else 'note', 'id': note.id, 'title': note.title or 'Untitled note'})
        return {'results': results}

    @router.get('/focus')
    def focus(request: Request):
        value = profile(require_user(request))
        return {'active': value.get('timer'), 'sessions': value.get('focus_sessions', []), 'server_time': time.time()}

    @router.post('/focus')
    def focus_action(request: Request, body: Timer):
        owner = require_user(request)
        with database() as conn:
            value = profile(owner, conn); now = time.time()
            if body.action == 'start':
                if value.get('timer'): raise HTTPException(409, 'A timer is already running. Stop it first.')
                value['timer'] = {'started': now, 'project': body.project.strip() or 'Focus', 'kind': body.kind, 'minutes': body.minutes}
            else:
                timer = value.get('timer')
                if not timer: raise HTTPException(409, 'No timer is running')
                elapsed = max(0, now - timer['started'])
                if timer['kind'] == 'pomodoro': elapsed = min(elapsed, timer['minutes'] * 60)
                value['focus_sessions'] = (value.get('focus_sessions', []) + [{**timer, 'ended': now, 'seconds': round(elapsed)}])[-500:]
                value['timer'] = None
            save(owner, value, conn)
        return {'active': value.get('timer'), 'sessions': value.get('focus_sessions', []), 'server_time': now}

    @router.get('/team')
    def team(request: Request):
        require_user(request)
        now = time.time()
        with database() as conn:
            people = []
            for row in conn.execute('SELECT owner,data FROM profiles'):
                value = json.loads(row['data'])
                if value.get('share_presence'):
                    people.append({'name': row['owner'], 'status': value.get('status', 'available'),
                                   'online': now - value.get('last_seen', 0) < 90})
            posts = [dict(r) for r in conn.execute('SELECT * FROM activity ORDER BY created DESC LIMIT 30')]
        return {'people': people, 'activity': posts}

    @router.post('/presence')
    def presence(request: Request):
        owner = require_user(request)
        with database() as conn:
            value = profile(owner, conn)
            if value.get('share_presence'):
                value['last_seen'] = time.time(); save(owner, value, conn)
        return {'ok': True}

    @router.post('/announcements')
    def announce(request: Request, body: Announcement):
        owner = require_user(request)
        if not body.body.strip(): raise HTTPException(422, 'Write an announcement first')
        with database() as conn:
            conn.execute('INSERT INTO activity VALUES (?,?,?,?)', (str(uuid.uuid4()), owner, body.body.strip(), time.time()))
            conn.workspace_events.add((owner, 'team'))
        return {'ok': True}

    @router.post('/goals')
    def goals(request: Request, body: Goal):
        owner = require_user(request)
        with database() as conn:
            value = profile(owner, conn); goals = value.get('goals', [])
            entry = body.model_dump(); entry['id'] = body.id or str(uuid.uuid4())
            if body.id and not any(g['id'] == body.id for g in goals): raise HTTPException(404, 'Goal not found')
            goals = [g for g in goals if g['id'] != entry['id']] + [entry]
            if len(goals) > 20: raise HTTPException(422, 'Use at most 20 goals')
            value['goals'] = goals; save(owner, value, conn)
        return {'goals': goals}

    @router.post('/shortcuts')
    def shortcuts(request: Request, body: Shortcut):
        owner = require_user(request)
        parsed = urlsplit(body.url)
        if parsed.scheme not in ('https', 'http') or not parsed.netloc or parsed.username or parsed.password:
            raise HTTPException(422, 'Use an http or https link without embedded credentials')
        with database() as conn:
            value = profile(owner, conn); links = value.get('shortcuts', [])
            if len(links) >= 30: raise HTTPException(422, 'Use at most 30 shortcuts')
            links.append({'id': str(uuid.uuid4()), **body.model_dump()})
            value['shortcuts'] = links; save(owner, value, conn)
        return {'shortcuts': links}

    @router.delete('/{collection}/{item_id}')
    def remove_personal(request: Request, collection: Literal['shortcuts', 'goals'], item_id: str):
        owner = require_user(request)
        with database() as conn:
            value = profile(owner, conn)
            value[collection] = [x for x in value.get(collection, []) if x['id'] != item_id]
            save(owner, value, conn)
        return {'ok': True}

    @router.get('/weather')
    async def weather(request: Request):
        value = profile(require_user(request))
        if not value.get('weather_enabled') or not value.get('city'):
            return {'configured': False}
        cache_key = (require_user(request), value['city'])
        cached = _weather_cache.get(cache_key)
        if cached and time.time() - cached[0] < 900: return cached[1]
        try:
            async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
                r = await client.get('https://geocoding-api.open-meteo.com/v1/search', params={'name': value['city'], 'count': 1})
                r.raise_for_status(); places = r.json().get('results', [])
                if not places: raise HTTPException(404, 'Location not found. Try city and country.')
                place = places[0]
                r = await client.get('https://api.open-meteo.com/v1/forecast', params={'latitude': place['latitude'], 'longitude': place['longitude'], 'current': 'temperature_2m,weather_code', 'models':'gfs_seamless'})
                r.raise_for_status(); data = r.json()
                result = {'configured': True, 'place': place['name'] + ', ' + place.get('country', ''), 'current': data['current'], 'units': data['current_units']}
                if len(_weather_cache) > 200: _weather_cache.clear()
                _weather_cache[cache_key] = (time.time(), result)
                return result
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(502, 'Weather is unavailable. Your other widgets are unaffected.') from exc
    return router
