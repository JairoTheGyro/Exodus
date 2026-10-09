"""Notes JSON import in disposable stores, with synthetic data and no network."""
import asyncio
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import socket
import tempfile
import tracemalloc
from types import SimpleNamespace
import unittest
from unittest.mock import patch

_temp = tempfile.TemporaryDirectory(prefix='exodus-notes-import-')
os.environ.update(ODYSSEUS_DATA_DIR=_temp.name, DATABASE_URL='sqlite:///' + _temp.name + '/notes.db',
                  AUTH_ENABLED='true', LOCALHOST_BYPASS='false')
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from core.database import Base, engine, SessionLocal, Note
from routes.note.note_routes import setup_note_routes
from src.ai_policy import WorkspacePolicyMiddleware, allowed_without_ai
from src.home_store import database, save
from src.note_export import build_note_export
from src import note_import as ni
from src.upload_handler import extract_internal_upload_ids

Base.metadata.create_all(engine)
app = FastAPI()
app.state.auth_manager = SimpleNamespace(is_configured=True)
app.add_middleware(WorkspacePolicyMiddleware)
@app.middleware('http')
async def identity(request, call_next):
    request.state.current_user = request.headers.get('x-test-user')
    return await call_next(request)
app.include_router(setup_note_routes())

STAMP = datetime(2026, 9, 30, 12, 34, 56, 123456)
ITEMS = [{'id': 'milk', 'text': 'Milk ☕', 'done': True, 'indent': 0},
         {'id': 'bread', 'text': 'Bread\nWhole grain', 'checked': False, 'indent': 1, 'due': '2026-10-01'}]


def envelope(*notes):
    return {'format': 'exodus.notes', 'version': 1, 'exported_at': STAMP.isoformat(), 'notes': list(notes)}


class ImportChecks(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)
        self.client.headers['x-test-user'] = 'importer'
        self.indexer = patch('src.note_indexing.enqueue_note')
        self.enqueued = self.indexer.start()
        self.events = patch('src.workspace_events.publish_workspace_event')
        self.published = self.events.start()
        self.addCleanup(self.indexer.stop)
        self.addCleanup(self.events.stop)
        with SessionLocal() as db:
            db.query(Note).filter(Note.owner.in_(('importer', 'exporter')) | (Note.id == 'foreign-original')).delete()
            db.add(Note(id='foreign-original', owner='someone-else', title='Keep private', ai_memory_enabled=False))
            db.commit()
        self.enqueued.reset_mock()
        self.published.reset_mock()
        with database() as db:
            save('importer', {'mode': 'ai-free'}, db)

    def imported(self):
        with SessionLocal() as db:
            return [dict(id=n.id, owner=n.owner, title=n.title, content=n.content,
                    items=json.loads(n.items) if n.items else None, tags=n.tags,
                    archived=n.archived, pinned=n.pinned, ai_memory_enabled=n.ai_memory_enabled,
                    source=n.source, image_url=n.image_url, color=n.color, session_id=n.session_id,
                    agent_session_id=n.agent_session_id, ai_classification=n.ai_classification,
                    due_date=n.due_date, repeat=n.repeat, created_at=n.created_at, updated_at=n.updated_at)
                    for n in db.query(Note).filter(Note.owner == 'importer').all()]

    def post(self, data, **kwargs):
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('No external request')), \
             patch('src.ai_policy.require_ai', side_effect=AssertionError('Import does not invoke AI')):
            return self.client.post('/api/notes/import/json', content=json.dumps(data).encode('utf-8'),
                                    headers={'content-type':'application/json'}, **kwargs)

    def test_real_export_import_metadata_privacy_and_owner_in_both_modes(self):
        with SessionLocal() as db:
            db.add(Note(id='export-original', owner='exporter', title='Groceries — café', content='buy avocados',
                items=json.dumps(ITEMS), note_type='checklist', label='Work Personal', color='blue',
                pinned=True, archived=True, ai_memory_enabled=False, created_at=STAMP, updated_at=STAMP,
                due_date='2026-10-01T09:30:00-04:00', repeat='weekly:4'))
            db.commit()
        with build_note_export('exporter', 'json') as stream:
            data = json.load(stream)
        for mode in ('full', 'ai-free'):
            with database() as db:
                save('importer', {'mode': mode}, db)
            self.enqueued.reset_mock()
            self.published.reset_mock()
            response = self.post(data)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['imported'], 1)
            row = self.imported()[-1]
            self.assertNotEqual(row['id'], 'export-original')
            self.assertEqual(row['owner'], 'importer')
            self.assertEqual(row['title'], 'Groceries — café')
            self.assertEqual(row['content'], 'buy avocados')
            self.assertEqual(row['items'], ITEMS)
            self.assertEqual(row['tags'], ['Work', 'Personal'])
            self.assertTrue(row['archived'])
            self.assertTrue(row['pinned'])
            self.assertFalse(row['ai_memory_enabled'])
            self.assertEqual(row['created_at'], STAMP)
            self.assertEqual(row['updated_at'], STAMP)
            self.assertEqual(row['due_date'], '2026-10-01T09:30:00-04:00')
            self.assertEqual(row['repeat'], 'weekly:4')
            self.assertEqual(self.enqueued.call_count, 1)
            self.published.assert_called_once_with('importer', 'notes')
        self.assertEqual(len(self.imported()), 2, 'Repeated imports intentionally create separate copies')
        self.assertEqual(len({r['id'] for r in self.imported()}), 2)
        with SessionLocal() as db:
            self.assertEqual(db.get(Note, 'foreign-original').title, 'Keep private')
            self.assertEqual(db.get(Note, 'export-original').owner, 'exporter')

    def test_discards_foreign_sessions_attachments_background_and_ai_actions(self):
        response = self.post(envelope(dict(id='foreign-original', owner='someone-else', title='Copy',
            content='File /api/upload/0123456789abcdef0123456789abcdef.txt and ordinary prose.',
            image_url='https://untrusted.invalid/tracker.png', color='bg:/uploads/other-owner.png',
            session_id='foreign-chat', agent_session_id='foreign-agent',
            ai_classification='{"task_prompt":"do something"}', ai_content_hash='not-current',
            items=[{'text':'Item','done':True,'agent_session_id':'foreign'}])))
        self.assertEqual(response.status_code, 200, response.text)
        row = self.imported()[0]
        self.assertEqual(row['content'], 'File [attachment not imported] and ordinary prose.')
        for key in ('image_url', 'color', 'session_id', 'agent_session_id', 'ai_classification'):
            self.assertIsNone(row[key], key)
        self.assertFalse(row['ai_memory_enabled'], 'Old exports must not silently opt into memory')
        self.assertEqual(row['source'], 'import')
        self.assertNotIn('agent_session_id', row['items'][0])
        self.assertGreater(len(response.json()['warnings']), 3)

    def test_malformed_rows_reject_whole_file_before_any_write(self):
        cases = [None, [], {'title':{}}, {'content':123}, {'archived':'false'},
                 {'archived':True,'is_archived':False}, {'ai_memory_enabled':None},
                 {'tags':['two words']}, {'tags':[123]}, {'items':'not json'},
                 {'items':[1]}, {'items':[{'text':'ok','done':'false'}]}, {'items':[{'text':'ok','id':'unsafe"id'}]},
                 {'created_at':'invalid'}, {'due_date':'tomorrow'}, {'sort_order':False},
                 {'repeat':'javascript:alert(1)'}, {'unknown':'not v1'}, {'content':'\ud800'}]
        for bad in cases:
            with self.subTest(bad=repr(bad)):
                response = self.post(envelope({'title':'must not save'}, bad))
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(self.imported(), [])
        self.enqueued.assert_not_called()
        self.published.assert_not_called()

    def test_invalid_envelopes_versions_json_and_auth_are_rejected(self):
        for data in [[], {}, {'notes':[]}, envelope() | {'version':True},
                     envelope() | {'version':2}, envelope() | {'format':'other'}, envelope() | {'notes':{}}]:
            self.assertEqual(self.post(data).status_code, 422)
        for body in [b'not json', b'{"format":"exodus.notes","version":1,"version":2,"notes":[]}',
                     b'{"format":"exodus.notes","version":1,"notes":[{"sort_order":NaN}]}']:
            self.assertEqual(self.client.post('/api/notes/import/json', content=body).status_code, 422)
        self.client.headers.pop('x-test-user')
        self.assertEqual(self.post(envelope({'title':'no identity'})).status_code, 401)
        self.assertEqual(self.imported(), [])
        self.assertTrue(allowed_without_ai('/api/notes/import/json', 'POST'))
        self.assertFalse(allowed_without_ai('/api/notes/import/json', 'GET'))
        self.assertFalse(allowed_without_ai('/api/notes/import/other', 'POST'))

    def test_request_size_record_limit_and_chunked_body_are_bounded(self):
        with patch.object(ni, 'MAX_IMPORT_BYTES', 100):
            self.assertEqual(self.post(envelope({'content':'x' * 101})).status_code, 413)
        with patch.object(ni, 'MAX_IMPORT_NOTES', 2):
            self.assertEqual(self.post(envelope({}, {}, {})).status_code, 413)
        read = []
        async def chunks():
            for chunk in (b'12345', b'123456', b'not consumed'):
                read.append(chunk)
                yield chunk
        request = SimpleNamespace(headers={}, stream=chunks)
        with patch.object(ni, 'MAX_IMPORT_BYTES', 10):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(ni.read_import_body(request))
        self.assertEqual(caught.exception.status_code, 413)
        self.assertEqual(len(read), 2)
        self.assertEqual(self.imported(), [])
        self.enqueued.assert_not_called()

    def test_aggregate_checklist_budget_precedes_normalization_and_writes(self):
        data = envelope({'items': json.dumps([{}, {}])}, {'items': [{}, {}]})
        with patch.object(ni, 'MAX_IMPORT_ITEMS', 3), \
             patch.object(ni.uuid, 'uuid4', side_effect=AssertionError('No IDs before aggregate validation')):
            response = self.post(data)
        self.assertEqual(response.status_code, 413, response.text)
        self.assertEqual(self.imported(), [])
        self.enqueued.assert_not_called()
        self.published.assert_not_called()

    def test_millions_of_tiny_items_are_rejected_before_json_allocation(self):
        # Three million empty items fit inside the byte/row/per-note limits.
        # Construct bytes before measuring, never construct three million dicts.
        row = b'{"items":[' + b'{},' * 4999 + b'{}]}'
        payload = b'{"format":"exodus.notes","version":1,"notes":[' + b','.join([row] * 600) + b']}'
        self.assertLess(len(payload), ni.MAX_IMPORT_BYTES)
        tracemalloc.start()
        try:
            with patch.object(ni.json, 'loads', side_effect=AssertionError('Reject before JSON allocation')), \
                 patch.object(ni.uuid, 'uuid4', side_effect=AssertionError('Reject before UUID normalization')):
                with self.assertRaises(HTTPException) as caught:
                    ni.validate_import(payload)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertEqual(caught.exception.status_code, 413)
        self.assertLess(peak, 24 * 1024 * 1024)
        self.assertEqual(self.imported(), [])
        self.enqueued.assert_not_called()
        self.published.assert_not_called()

    def test_encoded_checklists_use_strict_parser_and_shared_budget(self):
        for items in ('[{"text":"first","text":"duplicate"}]', '[{"indent":NaN}]'):
            with self.subTest(items=items):
                self.assertEqual(self.post(envelope({'items': items})).status_code, 422)
        self.assertEqual(self.imported(), [])
        self.assertEqual(self.post(envelope({'items': '[' * 33 + ']' * 33})).status_code, 422)
        with patch.object(ni, 'MAX_IMPORT_ITEMS', 4):
            response = self.post(envelope({'items': json.dumps(ITEMS)}, {'items': ITEMS}))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([r['items'] for r in self.imported()], [ITEMS, ITEMS])

    def test_all_canonical_attachment_forms_are_inert_in_every_imported_text(self):
        upload_id = '0123456789abcdef0123456789abcdef.pdf'
        forms = [f'https://old.invalid/api/upload/{upload_id}',
                 f'odysseus://attachment/{upload_id}',
                 f'[Attachment: Other owner file | id={upload_id} | mime=application/pdf]',
                 f'<!-- pdf_source upload_id="{upload_id}" -->',
                 f"<!-- pdf_form_source upload_id='{upload_id}' page='1' -->"]
        for mode in ('full', 'ai-free'):
            with database() as db:
                save('importer', {'mode': mode}, db)
            data = envelope(*[{'title': text, 'content': text, 'items': [{'text': text}],
                               'tags': [f'/api/upload/{upload_id}', 'safe'], 'ai_memory_enabled': False}
                              for text in forms])
            response = self.post(data)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['imported'], len(forms))
            self.assertTrue(response.json()['warnings'])
        for row in self.imported():
            for text in [row['title'], row['content'], row['items'][0]['text'], *row['tags']]:
                self.assertFalse(extract_internal_upload_ids(text), text)
            self.assertEqual(row['tags'], ['safe'])
            self.assertFalse(row['ai_memory_enabled'])

    def test_adversarial_incomplete_attachment_markers_and_plain_urls(self):
        # Many repeated starts with no closing marker must not trigger repeated
        # scans of the entire remaining text in any canonical regex.
        text = ('https://example.invalid/' * 20000 + '\n' +
                '[Attachment:name ' * 20000 + '\n' + '<!-- pdf_source ' * 20000)
        records, warnings = ni.validate_import(json.dumps(envelope({'content': text})).encode())
        cleaned = records[0]['content']
        self.assertTrue(cleaned.startswith('https://example.invalid/' * 20000))
        self.assertNotIn('[Attachment:', cleaned)
        self.assertNotIn('<!-- pdf_source', cleaned)
        self.assertFalse(extract_internal_upload_ids(cleaned))
        self.assertEqual(warnings['attachment_references'], 40000)

    def test_failed_transaction_rolls_back_all_notes_and_hooks(self):
        with patch.object(ni.uuid, 'uuid4', return_value='intentional-test-collision'):
            response = self.post(envelope({'title':'first'},{'title':'second'}))
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.imported(), [])
        self.enqueued.assert_not_called()
        self.published.assert_not_called()

    def test_timezone_normalization_empty_import_and_archive_visibility(self):
        self.assertEqual(self.post(envelope()).json()['imported'], 0)
        self.assertEqual(self.post(envelope({'title':'old','is_archived':True,
            'created_at':'2026-10-01T09:30:00-04:00','updated_at':'2026-10-01T13:30:00Z'})).status_code, 200)
        row = self.imported()[0]
        self.assertEqual(row['created_at'], datetime(2026,10,1,13,30))
        self.assertEqual(row['updated_at'], row['created_at'])
        self.assertEqual(self.client.get('/api/notes').json()['notes'], [])
        self.assertEqual(self.client.get('/api/notes?archived=true').json()['notes'][0]['id'], row['id'])


if __name__ == '__main__':
    unittest.main()
