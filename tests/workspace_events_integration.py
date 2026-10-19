"""Disposable real HTTP/SSE + database invalidation checks, no operator data.

Runs a loopback uvicorn fixture and real Notes/Library/Calendar API mutations.
No model, credentials, mail server, or companion service is used.
"""
import asyncio
import json
import os
from pathlib import Path
import queue
import socket
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_temp = tempfile.TemporaryDirectory(prefix='exodus-events-test-')
os.environ.update(ODYSSEUS_DATA_DIR=_temp.name, DATABASE_URL='sqlite:///' + _temp.name + '/test.db',
                  EXODUS_DOCUMENTS_DIR=_temp.name + '/documents', AUTH_ENABLED='true',
                  LOCALHOST_BYPASS='false', ODYSSEUS_INPROCESS_POLLERS='0', PYTHON_DOTENV_DISABLED='1')
import httpx
import uvicorn
from fastapi import FastAPI
from sqlalchemy import bindparam, update
from core.database import SessionLocal, Note, CalendarCal, CalendarEvent, DocumentFile
from routes.note.note_routes import setup_note_routes
from routes.calendar_routes import setup_calendar_routes
from routes.document.document_routes import setup_document_routes
from routes.home_routes import setup_home_routes
from routes.workspace_event_routes import setup_workspace_event_routes
from src.ai_policy import WorkspacePolicyMiddleware
from src.home_store import database, profile, save
from src.workspace_events import subscribe_workspace_events, publish_workspace_event

app = FastAPI()
app.state.auth_manager = SimpleNamespace(is_configured=True, get_privileges=lambda _: {'can_use_documents': True})
app.add_middleware(WorkspacePolicyMiddleware)
@app.middleware('http')
async def identity(request, call_next):
    request.state.current_user = request.headers.get('x-test-user')
    return await call_next(request)
from routes.local_document_routes import router as library_files_router
for router in (setup_note_routes(), setup_calendar_routes(), setup_document_routes(None),
               library_files_router, setup_home_routes(), setup_workspace_event_routes()):
    app.include_router(router)


class LiveStream:
    def __init__(self, base, owner):
        self.owner = owner
        self.events = queue.Queue()
        self.response = None
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._read, args=(base, owner), daemon=True)
        self.thread.start()
        event = self.events.get(timeout=5)
        if event != ('ready', {}):
            raise AssertionError(event)

    def _read(self, base, owner):
        try:
            with httpx.Client(timeout=20) as client:
                with client.stream('GET', base + '/api/workspace/events', headers={'x-test-user': owner}) as response:
                    self.response = response
                    response.raise_for_status()
                    event = None
                    for line in response.iter_lines():
                        if self.done.is_set():
                            break
                        if line.startswith('event: '): event = line[7:]
                        if line.startswith('data: '): self.events.put((event, json.loads(line[6:])))
        except Exception as exc:
            if not self.done.is_set(): self.events.put(('error', str(exc)))

    def wait_for(self, topic):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            event, payload = self.events.get(timeout=max(.01, deadline-time.monotonic()))
            if event == 'error': raise AssertionError(payload)
            if event == 'change':
                if set(payload) != {'topic'}: raise AssertionError('Event leaked data')
                if payload['topic'] == topic: return
        raise AssertionError('Missing event: ' + topic)

    def clear(self):
        while not self.events.empty(): self.events.get_nowait()

    def close(self):
        self.done.set()
        # Wake the streaming reader so it exits its response context cleanly.
        publish_workspace_event(self.owner, 'notes')
        self.thread.join(timeout=2)
        if self.response: self.response.close()


class WorkspaceEventsChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.note_patch = patch('src.note_indexing.enqueue_note')
        cls.note_patch.start()
        cls.sock = socket.socket()
        cls.sock.bind(('127.0.0.1', 0))
        cls.base = 'http://127.0.0.1:' + str(cls.sock.getsockname()[1])
        cls.server = uvicorn.Server(uvicorn.Config(app, log_level='error', timeout_graceful_shutdown=1))
        cls.thread = threading.Thread(target=cls.server.run, kwargs={'sockets': [cls.sock]}, daemon=True)
        cls.thread.start()
        for _ in range(100):
            if cls.server.started: break
            time.sleep(.02)
        assert cls.server.started
        cls.client = httpx.Client(base_url=cls.base, headers={'x-test-user':'alice'}, timeout=10)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.server.should_exit = True
        cls.thread.join(timeout=4)
        cls.note_patch.stop()

    def setUp(self):
        self.alice = LiveStream(self.base, 'alice')
        self.bob = LiveStream(self.base, 'bob')

    def tearDown(self):
        self.alice.close(); self.bob.close()

    def test_live_api_crud_streams_owner_scoped_in_both_modes(self):
        for mode in ('full', 'ai-free'):
            self.assertEqual(self.client.patch('/api/home/profile', json={'mode':mode}).status_code, 200)
            self.alice.wait_for('profile')
            self.alice.clear()
            note = self.client.post('/api/notes', json={'title':'SSE note', 'content':'Private test body'} )
            self.assertEqual(note.status_code, 200, note.text)
            nid = note.json()['id']
            self.alice.wait_for('notes')
            self.assertEqual(self.client.put('/api/notes/' + nid, json={'content':'Updated body'}).status_code, 200)
            self.alice.wait_for('notes')
            self.assertEqual(self.client.delete('/api/notes/' + nid).status_code, 200)
            self.alice.wait_for('notes')
            doc = self.client.post('/api/documents/upload', files={'file':('event.md', b'# File', 'text/markdown')})
            self.assertEqual(doc.status_code, 201, doc.text)
            self.alice.wait_for('documents')
            self.assertEqual(self.client.delete('/api/documents/' + doc.json()['id']).status_code, 200)
            self.alice.wait_for('documents')
            ev = self.client.post('/api/calendar/events', json={'summary':'Event', 'dtstart':'2026-10-01T10:00:00', 'dtend':'2026-10-01T11:00:00'})
            self.assertEqual(ev.status_code, 200, ev.text)
            self.alice.wait_for('calendar')
            uid = ev.json()['uid']
            self.assertEqual(self.client.put('/api/calendar/events/' + uid, json={'summary':'Changed event'}).status_code, 200)
            self.alice.wait_for('calendar')
            self.assertEqual(self.client.delete('/api/calendar/events/' + uid).status_code, 200)
            self.alice.wait_for('calendar')
            # Independent authenticated stream receives no owner metadata or changes.
            with self.assertRaises(queue.Empty): self.bob.events.get(timeout=.15)
        self.assertEqual(httpx.get(self.base+'/api/workspace/events').status_code, 401)

    def test_orm_tools_bulk_and_transaction_rollbacks(self):
        with SessionLocal() as db:
            db.add(Note(id='rolled-back', owner='alice', title='discard'))
            db.flush(); db.rollback()
        with self.assertRaises(queue.Empty): self.alice.events.get(timeout=.15)
        with SessionLocal() as db:
            db.add(Note(id='agent-note', owner='alice', title='tool wrote this'))
            db.commit()
        self.alice.wait_for('notes')
        with SessionLocal() as db:
            db.query(Note).filter(Note.id=='agent-note').update({'title':'bulk edit'})
            db.commit()
        self.alice.wait_for('notes')
        with SessionLocal() as db:
            db.execute(update(Note).where(Note.id == bindparam('chosen_id')).values(title='bound edit'),
                       {'chosen_id':'agent-note'}, execution_options={'synchronize_session':False})
            db.commit()
        self.alice.wait_for('notes')
        with SessionLocal() as db:
            db.execute(update(Note), [{'id':'agent-note', 'title':'batch edit'}])
            db.commit()
        self.alice.wait_for('notes')
        with SessionLocal() as db:
            with db.begin_nested():
                db.add(Note(id='nested-note', owner='alice', title='nested'))
                db.flush()
            db.rollback()
        with self.assertRaises(queue.Empty): self.alice.events.get(timeout=.15)
        with SessionLocal() as db:
            db.add(Note(id='outer-note', owner='alice', title='outer'))
            db.flush()
            savepoint=db.begin_nested()
            db.add(Note(id='nested-bob', owner='bob', title='discard'))
            db.flush(); savepoint.rollback(); db.commit()
        self.alice.wait_for('notes')
        with self.assertRaises(queue.Empty): self.bob.events.get(timeout=.15)
        with SessionLocal() as db:
            db.query(Note).filter(Note.id=='agent-note').delete(synchronize_session=False)
            db.commit()
        self.alice.wait_for('notes')

    def test_profile_goals_focus_commit_and_rollback(self):
        with database() as db:
            value=profile('alice', db)
            value.update(goals=[{'id':'g1'}], timer={'started':1})
            save('alice', value, db)
        seen = set()
        for _ in range(3):
            kind, payload = self.alice.events.get(timeout=5)
            self.assertEqual(kind, 'change')
            seen.add(payload['topic'])
        self.assertEqual(seen, {'profile', 'goals', 'focus'})
        with self.assertRaises(RuntimeError), database() as db:
            value=profile('alice', db); value['timer']=None
            save('alice', value, db)
            raise RuntimeError('discard profile save')
        with self.assertRaises(queue.Empty): self.alice.events.get(timeout=.15)

    def test_mail_cache_write_update_delete(self):
        from routes.email_helpers import _init_scheduled_db
        from routes.email_routes import _email_index_upsert, _email_index_update_flags, _email_index_delete
        _init_scheduled_db()
        _email_index_upsert('alice', None, 'INBOX', [{'uid':'42','subject':'Private mail','flags':''}])
        self.alice.wait_for('inbox')
        _email_index_update_flags('alice', None, 'INBOX', '42', '\\Seen', True)
        self.alice.wait_for('inbox')
        _email_index_delete('alice', None, 'INBOX', '42')
        self.alice.wait_for('inbox')
        with self.assertRaises(queue.Empty): self.bob.events.get(timeout=.15)

    def test_bounded_slow_subscriber_and_worker_thread(self):
        async def check():
            sub=subscribe_workspace_events({'isolated'})
            def publish_many():
                for _ in range(200): publish_workspace_event('isolated', 'notes')
            worker=threading.Thread(target=publish_many);worker.start();worker.join()
            await asyncio.sleep(.01)
            self.assertLessEqual(sub.queue.qsize(),64)
            seen=[]
            while not sub.queue.empty(): seen.append(sub.queue.get_nowait())
            self.assertIn('reconnect',seen)
            sub.close()
            publish_workspace_event('isolated', 'notes')
            await asyncio.sleep(.01)
            self.assertTrue(sub.queue.empty())
        asyncio.run(check())


if __name__=='__main__': unittest.main(verbosity=2)
