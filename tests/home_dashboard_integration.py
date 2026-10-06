"""Disposable Home scratchpad/recent-content/telemetry API checks.

Run in an isolated Python process. Uses temporary stores, a mocked Vaultwarden
health response and a captured note-index queue; never uses a real model or mail.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TEMP = tempfile.TemporaryDirectory(prefix='exodus-dashboard-tests-')
ROOT = Path(_TEMP.name)
os.environ['ODYSSEUS_DATA_DIR'] = str(ROOT / 'data')
os.environ['DATABASE_URL'] = 'sqlite:///' + str(ROOT / 'data' / 'app.db')
os.environ['EXODUS_SCRATCHPAD_DIR'] = str(ROOT / 'scratchpad')
os.environ['EXODUS_DOCUMENTS_DIR'] = str(ROOT / 'documents')
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
os.environ['AUTH_ENABLED'] = 'true'
os.environ['LOCALHOST_BYPASS'] = 'false'

from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.database import Base, engine, SessionLocal, Note, Document, DocumentFile
from routes.home_routes import setup_home_routes
from routes.document.document_routes import setup_document_routes
from src.ai_policy import WorkspacePolicyMiddleware
from src.home_store import database
from src import home_diagnostics as hd
from src.scratchpad import ScratchpadStore, ScratchpadConflict

Base.metadata.create_all(engine)
app = FastAPI()
app.state.auth_manager = SimpleNamespace(is_configured=True, get_privileges=lambda owner: {'can_use_documents': True})
app.add_middleware(WorkspacePolicyMiddleware)
@app.middleware('http')
async def identity(request, call_next):
    request.state.current_user = request.headers.get('x-test-user')
    return await call_next(request)
app.include_router(setup_home_routes())
app.include_router(setup_document_routes(None))


def vault_reply():
    return {'status': 'running', 'detail': 'Test service health only.', 'sync': {'status': 'unknown'}}


class DashboardChecks(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(os.environ['EXODUS_SCRATCHPAD_DIR'], ignore_errors=True)
        self.indexed = []
        self.index_patch = patch('src.note_indexing.enqueue_note', side_effect=lambda *args: self.indexed.append(args))
        self.index_patch.start()
        self.client = TestClient(app)
        self.client.headers['x-test-user'] = 'admin'
        with SessionLocal() as db:
            for model in (Document, DocumentFile, Note):
                db.query(model).delete()
            db.commit()
        with database() as db:
            db.execute('DELETE FROM profiles')
        self.store = ScratchpadStore()

    def tearDown(self):
        self.index_patch.stop()
        self.client.close()

    def save_text(self, text):
        current = self.client.get('/api/home/scratchpad').json()
        response = self.client.put('/api/home/scratchpad', json={'text': text, 'revision': current['revision']})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_persistence_utf8_private_permissions_and_both_modes(self):
        for mode in ('full', 'ai-free'):
            self.client.patch('/api/home/profile', json={'mode': mode})
            value = self.save_text('Café thoughts 📝\n\nNo model required: ' + mode)
            self.assertEqual(ScratchpadStore().read('admin'), value)
            path = Path(os.environ['EXODUS_SCRATCHPAD_DIR']) / 'scratchpad.md'
            self.assertEqual(path.read_text(), value['text'])
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(self.client.get('/api/home/scratchpad').headers['cache-control'], 'no-store')

    def test_authentication_and_account_isolation(self):
        private = self.save_text('Only admin sees this')
        self.client.headers['x-test-user'] = '../../another-user'
        self.assertEqual(self.client.get('/api/home/scratchpad').json()['text'], '')
        self.save_text('Separate pad')
        self.assertEqual(self.store.read('admin'), private)
        self.assertEqual(self.store.read('../../another-user')['text'], 'Separate pad')
        self.client.headers.pop('x-test-user')
        for method, url, body in [('get', '/api/home/scratchpad', None),
                                  ('get', '/api/home/diagnostics', None),
                                  ('put', '/api/home/scratchpad', private),
                                  ('post', '/api/home/scratchpad/to-note', {'revision': private['revision'], 'request_id': str(uuid.uuid4())})]:
            response = getattr(self.client, method)(url, **({'json': body} if body else {}))
            self.assertEqual(response.status_code, 401)

    def test_stale_revision_and_byte_limit_keep_saved_text(self):
        original = self.client.get('/api/home/scratchpad').json()
        saved = self.save_text('Fresh value')
        response = self.client.put('/api/home/scratchpad', json={'text': 'Stale edit', 'revision': original['revision']})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['detail']['current'], saved)
        response = self.client.put('/api/home/scratchpad', json={'text': 'a' * 20001, 'revision': saved['revision']})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.store.read('admin'), saved)

    def test_atomic_write_failure_keeps_existing_markdown(self):
        saved = self.save_text('Safe old text')
        with patch('src.scratchpad.os.replace', side_effect=OSError('disk failed')):
            response = self.client.put('/api/home/scratchpad', json={'text': 'New text', 'revision': saved['revision']})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.store.read('admin'), saved)
        self.assertEqual({p.name for p in Path(os.environ['EXODUS_SCRATCHPAD_DIR']).glob('.scratchpad-*')}, {'.scratchpad-owner.json', '.scratchpad-state.json'})

    def test_two_writers_cannot_overwrite_each_other(self):
        original = self.store.read('admin')
        def write(text):
            try:
                return self.store.write('admin', text, original['revision'])
            except ScratchpadConflict:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, ['First concurrent edit', 'Second concurrent edit']))
        self.assertEqual(sum(value is not None for value in results), 1)
        self.assertIn(self.store.read('admin')['text'], ['First concurrent edit', 'Second concurrent edit'])

    def test_note_conversion_and_retry_in_both_modes(self):
        for mode in ('full', 'ai-free'):
            self.client.patch('/api/home/profile', json={'mode': mode})
            saved = self.save_text('Captured title ' + mode + '\n- bullet one\n- bullet two')
            payload = {'revision': saved['revision'], 'request_id': str(uuid.uuid4())}
            result = self.client.post('/api/home/scratchpad/to-note', json=payload)
            self.assertEqual(result.status_code, 200, result.text)
            value = result.json()
            self.assertTrue(value['cleared'])
            self.assertFalse(value['replayed'])
            self.assertEqual(value['text'], '')
            with SessionLocal() as db:
                note = db.get(Note, value['id'])
                self.assertEqual(note.content, saved['text'])
                self.assertEqual(note.tags, ['quick-capture'])
                self.assertEqual(note.owner, 'admin')
            self.assertIn((value['id'], 'admin'), self.indexed)
            retry = self.client.post('/api/home/scratchpad/to-note', json=payload).json()
            self.assertTrue(retry['replayed'])
            self.assertEqual(retry['id'], value['id'])
        with SessionLocal() as db:
            self.assertEqual(db.query(Note).count(), 2)

    def test_conversion_retry_preserves_later_edits(self):
        saved = self.save_text('First thought')
        payload = {'revision': saved['revision'], 'request_id': str(uuid.uuid4())}
        self.client.post('/api/home/scratchpad/to-note', json=payload)
        newer = self.save_text('Next thought typed while a response was lost')
        replay = self.client.post('/api/home/scratchpad/to-note', json=payload).json()
        self.assertTrue(replay['replayed'])
        self.assertFalse(replay['cleared'])
        self.assertEqual(replay['text'], newer['text'])
        self.assertEqual(self.store.read('admin'), newer)

    def test_same_text_saved_after_conversion_is_not_cleared_by_old_retry(self):
        saved = self.save_text('Same text, separate thought')
        payload = {'revision': saved['revision'], 'request_id': str(uuid.uuid4())}
        self.client.post('/api/home/scratchpad/to-note', json=payload)
        later = self.save_text(saved['text'])
        self.assertNotEqual(later['revision'], saved['revision'])
        response = self.client.post('/api/home/scratchpad/to-note', json=payload).json()
        self.assertTrue(response['replayed'])
        self.assertFalse(response['cleared'])
        self.assertEqual(self.store.read('admin'), later)

    def test_interrupted_metadata_save_recovers_revision_without_losing_text(self):
        before = self.save_text('Old content')
        from src.scratchpad import _write_json
        def fail_state(path, value):
            if path.name == '.scratchpad-state.json':
                raise OSError('interrupted')
            return _write_json(path, value)
        with patch('src.scratchpad._write_json', side_effect=fail_state):
            response = self.client.put('/api/home/scratchpad', json={'text': 'New durable content', 'revision': before['revision']})
        self.assertEqual(response.status_code, 503)
        after = self.store.read('admin')
        self.assertEqual(after['text'], 'New durable content')
        self.assertNotEqual(before['revision'], after['revision'])

    def test_commit_then_clear_failure_is_retryable_without_duplicate(self):
        saved = self.save_text('Durable note even if pad clear fails')
        payload = {'revision': saved['revision'], 'request_id': str(uuid.uuid4())}
        from src.scratchpad import _atomic_write
        def fail_clear(path, content):
            if path.name == 'scratchpad.md' and not content:
                raise OSError('disk full')
            return _atomic_write(path, content)
        with patch('src.scratchpad._atomic_write', side_effect=fail_clear):
            response = self.client.post('/api/home/scratchpad/to-note', json=payload)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.store.read('admin'), saved)
        replay = self.client.post('/api/home/scratchpad/to-note', json=payload).json()
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['text'], '')
        with SessionLocal() as db:
            self.assertEqual(db.query(Note).count(), 1)

    def test_failed_note_commit_never_clears_pad(self):
        saved = self.save_text('Keep on failed database commit')
        with patch.object(SessionLocal.class_, 'commit', side_effect=RuntimeError('test failure')):
            with self.assertRaises(RuntimeError):
                self.store.to_note('admin', saved['revision'], uuid.uuid4(), SessionLocal, Note)
        self.assertEqual(self.store.read('admin'), saved)
        with SessionLocal() as db:
            self.assertEqual(db.query(Note).count(), 0)

    def test_deleted_converted_note_is_not_resurrected_on_retry(self):
        saved = self.save_text('Once saved')
        payload = {'revision': saved['revision'], 'request_id': str(uuid.uuid4())}
        result = self.client.post('/api/home/scratchpad/to-note', json=payload).json()
        with SessionLocal() as db:
            db.delete(db.get(Note, result['id']))
            db.commit()
        self.assertEqual(self.client.post('/api/home/scratchpad/to-note', json=payload).status_code, 410)

    def test_unowned_existing_pad_is_not_claimed_by_a_new_account(self):
        root = Path(os.environ['EXODUS_SCRATCHPAD_DIR'])
        root.mkdir(parents=True)
        (root / 'scratchpad.md').write_text('Unowned legacy content')
        self.assertEqual(self.client.get('/api/home/scratchpad').status_code, 503)
        self.assertFalse((root / '.scratchpad-owner.json').exists())
        self.assertEqual((root / 'scratchpad.md').read_text(), 'Unowned legacy content')

    def test_symlink_storage_rejected(self):
        self.save_text('Pad')
        path = Path(os.environ['EXODUS_SCRATCHPAD_DIR']) / 'scratchpad.md'
        target = ROOT / 'unrelated.txt'
        target.write_text('Do not replace')
        path.unlink()
        path.symlink_to(target)
        self.assertEqual(self.client.get('/api/home/scratchpad').status_code, 503)
        self.assertEqual(target.read_text(), 'Do not replace')

    def test_recent_uploads_notes_and_existing_documents_share_pin_list(self):
        with SessionLocal() as db:
            db.add_all([
                Note(id='note-1', owner='admin', title='Idea', content='Text'),
                Note(id='archived', owner='admin', title='Hidden', archived=True),
                Document(id='doc-1', owner='admin', title='Existing editor', current_content=''),
                DocumentFile(id='file-1', owner='admin', filename='local.csv', storage_name='abc', file_size=4, mime_type='text/csv'),
                DocumentFile(id='removed', owner='admin', filename='hidden.txt', storage_name='def', file_size=4, mime_type='text/plain', deletion_pending=True),
                Note(id='foreign', owner='other', title='Private'),
            ])
            db.commit()
        self.client.patch('/api/home/profile', json={'pins': ['doc-1', 'note:note-1', 'upload:file-1', 'note:foreign']})
        for mode in ('full', 'ai-free'):
            self.client.patch('/api/home/profile', json={'mode': mode})
            rows = {r['id']: r for r in self.client.get('/api/home/files').json()['files']}
            self.assertEqual(set(rows), {'doc-1', 'note:note-1', 'upload:file-1'})
            self.assertTrue(all(row['pinned'] for row in rows.values()))
            self.assertEqual(rows['upload:file-1']['source_id'], 'file-1')
            self.assertEqual(rows['note:note-1']['kind'], 'note')
        with SessionLocal() as db:
            db.get(Note, 'note-1').title = 'Updated idea'
            db.delete(db.get(DocumentFile, 'file-1'))
            db.commit()
        rows = {r['id']: r for r in self.client.get('/api/home/files').json()['files']}
        self.assertEqual(rows['note:note-1']['title'], 'Updated idea')
        self.assertNotIn('upload:file-1', rows)

    def test_actual_document_delete_removes_pinned_recent_and_search_in_both_modes(self):
        for mode in ('full', 'ai-free'):
            doc_id = 'soft-delete-' + mode
            with SessionLocal() as db:
                db.add(Document(id=doc_id, owner='admin', title='Delete regression ' + mode,
                                current_content='Distinct search text', language='markdown'))
                db.commit()
            self.client.patch('/api/home/profile', json={'mode': mode, 'pins': [doc_id]})
            before = {row['id']: row for row in self.client.get('/api/home/files').json()['files']}
            self.assertTrue(before[doc_id]['pinned'])
            self.assertIn(doc_id, [row['id'] for row in self.client.get('/api/home/search?q=regression').json()['results']])
            response = self.client.delete('/api/document/' + doc_id)
            self.assertEqual(response.status_code, 200, response.text)
            with SessionLocal() as db:
                self.assertFalse(db.get(Document, doc_id).is_active)
            self.assertNotIn(doc_id, [row['id'] for row in self.client.get('/api/home/files').json()['files']])
            self.assertNotIn(doc_id, [row['id'] for row in self.client.get('/api/home/search?q=regression').json()['results']])

    def test_diagnostics_accurate_rss_disk_and_actual_database_probes(self):
        self.store.read('admin')
        path = ROOT / 'test-mail.db'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE email_message_index (id INTEGER)')
            db.execute('CREATE TABLE email_body_preview_cache (id INTEGER)')
        db.close()
        expected = shutil.disk_usage(os.environ['EXODUS_SCRATCHPAD_DIR'])
        with patch.object(hd, 'SCHEDULED_EMAILS_DB', str(path)), patch.object(hd, 'current_rss_bytes', return_value=123456), patch.object(hd.VaultwardenService, 'status', new=AsyncMock(return_value=vault_reply())):
            response = self.client.get('/api/home/diagnostics')
        self.assertEqual(response.status_code, 200)
        value = response.json()
        self.assertEqual(value['memory']['rss_bytes'], 123456)
        self.assertEqual(value['memory']['scope'], 'Exodus process')
        self.assertEqual(value['disk']['total_bytes'], expected.total)
        self.assertLess(abs(value['disk']['free_bytes'] - expected.free), 8 * 1024 * 1024)
        for key in ('notes', 'calendar', 'mail_cache'):
            self.assertEqual(value['databases'][key]['status'], 'ok')
        self.assertEqual(value['databases']['vaultwarden']['sync_status'], 'unknown')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        # The real OS measurement reports current resident memory and positive bytes.
        self.assertGreater(hd.current_rss_bytes(), 0)

    def test_diagnostics_missing_corrupt_offline_never_exposes_details(self):
        missing = ROOT / 'not-created.db'
        with patch.object(hd, 'SCHEDULED_EMAILS_DB', str(missing)):
            self.assertEqual(hd._mail_probe()['status'], 'not_initialized')
            self.assertFalse(missing.exists())
        corrupt = ROOT / 'corrupt.db'
        corrupt.write_text('not sqlite')
        with patch.object(hd, 'SCHEDULED_EMAILS_DB', str(corrupt)), patch.object(hd, 'SessionLocal', side_effect=RuntimeError('password=secret')), patch.object(hd.VaultwardenService, 'status', new=AsyncMock(side_effect=RuntimeError('token=secret'))):
            value = self.client.get('/api/home/diagnostics').json()
        for key in ('notes', 'calendar', 'mail_cache', 'vaultwarden'):
            self.assertEqual(value['databases'][key]['status'], 'unavailable')
        self.assertNotIn('secret', json.dumps(value))


if __name__ == '__main__':
    unittest.main(verbosity=2)
