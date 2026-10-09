"""Account-owned note memory consent, with no model or real vector service."""
import io
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from notes_search_integration import app, SessionLocal, Note, database, save
from fastapi.testclient import TestClient
from routes.home_routes import setup_home_routes
from src import note_indexing as ni
from core import database as dbmod
from sqlalchemy import create_engine

app.include_router(setup_home_routes())


class NotePrivacyChecks(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.headers['x-test-user'] = 'privacy-test'
        self.queue = patch.object(ni, 'enqueue_note')
        self.enqueued = self.queue.start()
        with database() as db:
            save('privacy-test', {'mode': 'full'}, db)
        with SessionLocal() as db:
            db.query(Note).delete()
            db.commit()

    def tearDown(self):
        self.queue.stop()

    def create(self, **extra):
        r = self.client.post('/api/notes', json={'title': 'Groceries', 'content': 'buy avocados', **extra})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def hit(self, note_id):
        with SessionLocal() as db:
            note = db.get(Note, note_id)
            return {'kind': 'note', 'owner': note.owner, 'note_id': note.id,
                    'note_fingerprint': ni.note_fingerprint(note)}

    def test_per_note_consent_persists_and_denies_stale_hits(self):
        note = self.create()
        self.assertTrue(note['ai_memory_enabled'])
        old = self.hit(note['id'])
        self.assertTrue(ni.current_metadata(old))
        r = self.client.put('/api/notes/' + note['id'], json={'ai_memory_enabled': False})
        self.assertFalse(r.json()['ai_memory_enabled'])
        self.assertFalse(ni.current_metadata(old))
        self.assertFalse(self.client.get('/api/notes/' + note['id']).json()['ai_memory_enabled'])
        self.client.headers['x-test-user'] = 'another-person'
        self.assertEqual(self.client.put('/api/notes/' + note['id'], json={'ai_memory_enabled': True}).status_code, 404)

    def test_archived_setting_is_explicit_personal_and_requeues(self):
        note = self.create(is_archived=True)
        hit = self.hit(note['id'])
        self.assertFalse(ni.current_metadata(hit))
        r = self.client.patch('/api/home/profile', json={'ai_include_archived_notes': True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(ni.current_metadata(hit))
        self.enqueued.assert_any_call(note['id'], 'privacy-test')
        self.client.headers['x-test-user'] = 'another-person'
        self.assertNotIn('ai_include_archived_notes', self.client.get('/api/home/profile').json()['profile'])
        self.client.headers['x-test-user'] = 'privacy-test'
        self.client.put('/api/notes/' + note['id'], json={'ai_memory_enabled': False})
        self.assertFalse(ni.current_metadata(hit))

    def test_ai_free_skips_chroma_and_retry_even_with_archived_opt_in(self):
        note = self.create(is_archived=True)
        with database() as db:
            save('privacy-test', {'mode': 'ai-free', 'ai_include_archived_notes': True}, db)
        with patch('src.rag_singleton.get_rag_manager', side_effect=AssertionError('No vector connection')):
            self.assertEqual(ni.ingest_note(note['id'], 'privacy-test'), {'status': 'skipped', 'reason': 'ai_free'})
            self.assertFalse(ni.current_metadata(self.hit(note['id'])))
        self.enqueued.reset_mock()
        self.client.patch('/api/home/profile', json={'ai_include_archived_notes': False})
        self.enqueued.assert_called_once_with(note['id'], 'privacy-test')

    def test_disabled_note_removes_stale_vectors_without_embeddings(self):
        note = self.create(ai_memory_enabled=False)
        removed = []
        collection = SimpleNamespace(get=lambda **kw: {'ids': ['old-chunk']}, delete=lambda ids: removed.extend(ids))
        lane = SimpleNamespace(collection=collection, encode=lambda _: self.fail('Opt-out must not embed'))
        rag = SimpleNamespace(healthy=True, _lanes=[lane], _split_into_chunks=lambda *a, **kw: self.fail('No content chunks'))
        self.assertEqual(ni.ingest_note(note['id'], 'privacy-test', rag=rag)['status'], 'removed')
        self.assertEqual(removed, ['old-chunk'])

    def test_default_archive_denial_and_setting_revocation_do_not_need_chroma(self):
        note = self.create(is_archived=True)
        with database() as db:
            save('privacy-test', {'mode': 'full', 'ai_include_archived_notes': True}, db)
        hit = self.hit(note['id'])
        self.assertTrue(ni.current_metadata(hit))
        with patch.object(ni, 'reindex_owner_notes', side_effect=OSError('offline')):
            self.assertEqual(self.client.patch('/api/home/profile', json={'ai_include_archived_notes': False}).status_code, 200)
        self.assertFalse(ni.current_metadata(hit))

    def test_consent_local_in_both_modes_and_exports_preserve_it(self):
        for mode in ('full', 'ai-free'):
            with database() as db:
                save('privacy-test', {'mode': mode}, db)
            note = self.create(ai_memory_enabled=False)
            r = self.client.get('/api/notes/export/json')
            self.assertEqual(r.status_code, 200)
            row = next(n for n in r.json()['notes'] if n['id'] == note['id'])
            self.assertFalse(row['ai_memory_enabled'])

    def test_zip_archived_option_and_body_search(self):
        active = self.create()
        archived = self.create(is_archived=True)
        for mode in ('full', 'ai-free'):
            with database() as db:
                save('privacy-test', {'mode': mode}, db)
            for query, count in (('', 1), ('?include_archived=true', 2)):
                r = self.client.get('/api/notes/export/zip' + query)
                self.assertEqual(r.status_code, 200)
                with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                    self.assertIsNone(z.testzip())
                    self.assertEqual(len(z.namelist()), count)
            found = self.client.get('/api/notes?q=AVOCADO').json()['notes']
            self.assertEqual([n['id'] for n in found], [active['id']])

    def test_migration_is_additive_and_repeatable(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'old.db'
            with sqlite3.connect(path) as conn:
                conn.execute('CREATE TABLE notes(id TEXT, title TEXT)')
                conn.execute("INSERT INTO notes VALUES ('old', 'Keep this')")
            eng = create_engine('sqlite:///' + str(path))
            try:
                with patch.object(dbmod, 'engine', eng):
                    dbmod._migrate_note_memory_policy()
                    dbmod._migrate_note_memory_policy()
                with sqlite3.connect(path) as conn:
                    self.assertEqual(conn.execute('SELECT * FROM notes').fetchone(), ('old', 'Keep this', 1))
            finally:
                eng.dispose()


if __name__ == '__main__':
    unittest.main()
