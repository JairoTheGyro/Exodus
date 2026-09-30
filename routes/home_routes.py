"""Non-AI Home: owner-scoped views over existing content and real personal state."""
import json
import time
import uuid
from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit
import httpx
from fastapi import APIRouter, Request, HTTPException, Query
from pydantic import BaseModel, Field
from core.database import SessionLocal, Note, Document
from src.auth_helpers import require_user, require_privilege
from src.home_store import database, profile, save
from src.ai_policy import cancel_ai

_weather_cache = {}

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

    @router.get('/files')
    def files(request: Request):
        owner = require_privilege(request, 'can_use_documents')
        pins = profile(owner).get('pins', [])
        with SessionLocal() as db:
            query = db.query(Document).filter(Document.owner == (owner or None), Document.archived == False)
            rows = query.order_by(Document.updated_at.desc()).limit(12).all()
            pinned = query.filter(Document.id.in_(pins)).all() if pins else []
            by_id = {row.id: row for row in pinned + rows}
            return {'files': [{'id': r.id, 'title': r.title, 'language': r.language, 'updated': r.updated_at.isoformat()+'Z', 'pinned': r.id in pins} for r in by_id.values()]}

    @router.get('/search')
    def search(request: Request, q: str = Query(min_length=2, max_length=200)):
        owner = require_user(request)
        needle = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        results = []
        with SessionLocal() as db:
            try: require_privilege(request, 'can_use_documents'); docs_allowed = True
            except HTTPException: docs_allowed = False
            if docs_allowed:
                for doc in db.query(Document).filter(Document.owner == (owner or None), Document.archived == False,
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
