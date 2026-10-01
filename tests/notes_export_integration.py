"""Local export, privacy, portability, cleanup and memory regression checks.
Run with repository mounted in the existing Exodus image:
  python tests/notes_export_integration.py
All records live in a disposable SQLite database; no user data or models.
"""
import asyncio
import io
import json
import os
import socket
import sys
import threading
import tempfile
import tracemalloc
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_temp = tempfile.TemporaryDirectory(prefix='exodus-export-tests-')
os.environ.update(ODYSSEUS_DATA_DIR=_temp.name, DATABASE_URL='sqlite:///' + _temp.name + '/notes.db', AUTH_ENABLED='true', LOCALHOST_BYPASS='false')
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.database import Base, engine, SessionLocal, Note
from routes.note.note_routes import setup_note_routes
from src.ai_policy import WorkspacePolicyMiddleware, allowed_without_ai
from src.home_store import database, save
from src.note_export import build_note_export, NoteExportResponse

Base.metadata.create_all(engine)
app = FastAPI()
app.state.auth_manager = SimpleNamespace(is_configured=True)
app.add_middleware(WorkspacePolicyMiddleware)
@app.middleware('http')
async def identity(request, call_next):
    request.state.current_user = request.headers.get('x-test-user')
    return await call_next(request)
app.include_router(setup_note_routes())

ITEMS = [{'id':'a','text':'Milk ☕','done':True,'indent':0}, {'id':'b','text':'Bread\nWhole grain','done':False,'indent':1,'due':'2026-10-01'}]
STAMP = datetime(2026, 9, 30, 12, 34, 56, 123456)

def metadata(markdown):
    head, body = markdown.split('---\n', 2)[1:]
    return {line.split(': ',1)[0]: json.loads(line.split(': ',1)[1]) for line in head.strip().splitlines()}, body

class ExportChecks(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.headers['x-test-user'] = 'exporter'
        with database() as db:save('exporter', {'mode':'ai-free'}, db)
        with patch('src.note_indexing.enqueue_note'), SessionLocal() as db:
            db.query(Note).delete()
            db.add_all([
                Note(id='one', owner='exporter', title='../Shopping:\n--- café', content='Original body\nSecond line', label='Work Personal', note_type='checklist', items=json.dumps(ITEMS, ensure_ascii=False), created_at=STAMP, updated_at=STAMP, due_date='2026-10-01T09:30:00-04:00', image_url='/uploads/test.png', pinned=True),
                Note(id='two', owner='exporter', title='../Shopping:\n--- café', content='Second note', label='Personal'),
                Note(id='archived', owner='exporter', title='Old', archived=True, items='invalid legacy JSON'),
                Note(id='foreign', owner='someone-else', title='Never export this'),
                Note(id='legacy', owner=None, title='Unowned legacy note'),
            ]);db.commit()

    def download(self, format):
        with patch.object(socket.socket,'connect',side_effect=AssertionError('Export must be offline')), patch('src.ai_policy.require_ai',side_effect=AssertionError('Export must not use AI')):
            response = self.client.get('/api/notes/export/' + format)
        self.assertEqual(response.status_code,200,response.text[:100] if format=='json' else '')
        self.assertIn('attachment;', response.headers['content-disposition'])
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(int(response.headers['content-length']), len(response.content))
        return response

    def test_zip_portability_and_owner_scope_both_modes(self):
        for mode in ['ai-free', 'full']:
            with database() as db:save('exporter', {'mode':mode}, db)
            with zipfile.ZipFile(io.BytesIO(self.download('zip').content)) as archive:
                self.assertIsNone(archive.testzip())
                names=archive.namelist()
                self.assertEqual(len(names),2)
                self.assertEqual(len(set(names)),2)
                self.assertTrue(all('/' not in name and '\\' not in name and name.endswith('.md') for name in names))
                records = [metadata(archive.read(name).decode()) for name in names]
                record, body = next(row for row in records if row[0]['id']=='one')
                self.assertEqual(record['title'], '../Shopping:\n--- café')
                self.assertEqual(record['tags'], ['Work','Personal'])
                self.assertEqual(record['category'], 'Reminders')
                self.assertEqual(json.loads(record['items']), ITEMS)
                self.assertEqual(record['created_at'], STAMP.isoformat())
                self.assertEqual(record['updated_at'], STAMP.isoformat())
                self.assertEqual(record['due_date'], '2026-10-01T09:30:00-04:00')
                self.assertIn('Original body\nSecond line', body)
                self.assertIn('- [x] Milk ☕', body)
                self.assertIn('    - [ ] Bread\n          Whole grain', body)
                self.assertEqual(next(r[0]['category'] for r in records if r[0]['id']=='two'), 'Personal')

    def test_json_preserves_all_columns_including_archived(self):
        for mode in ['ai-free','full']:
            with database() as db:save('exporter',{'mode':mode},db)
            dump=self.download('json').json()
            self.assertEqual(dump['version'],1)
            rows={r['id']:r for r in dump['notes']}
            self.assertEqual(set(rows), {'one','two','archived'})
            self.assertEqual(rows['archived']['items'], 'invalid legacy JSON')
            self.assertTrue(rows['archived']['is_archived'])
            with SessionLocal() as db:
                for note in db.query(Note).filter(Note.owner=='exporter'):
                    for col in Note.__table__.columns:
                        value=getattr(note,col.name)
                        if isinstance(value,datetime):value=value.isoformat()
                        self.assertEqual(rows[note.id][col.name],value,col.name)
            self.assertEqual(json.loads(rows['one']['items']),ITEMS)

    def test_auth_empty_exports_and_no_broader_ai_allowlist(self):
        self.client.headers.pop('x-test-user')
        for format in ['zip','json']:
            self.assertEqual(self.client.get('/api/notes/export/'+format).status_code,401)
        self.client.headers['x-test-user']='empty'
        self.assertEqual(self.download('json').json()['notes'],[])
        with zipfile.ZipFile(io.BytesIO(self.download('zip').content)) as archive:self.assertEqual(archive.namelist(),[])
        self.assertFalse(allowed_without_ai('/api/notes/export/zip','POST'))
        self.assertFalse(allowed_without_ai('/api/notes/export/ai','GET'))

    def test_failure_and_disconnect_close_temporary_files(self):
        real_tempfile=tempfile.TemporaryFile
        opened=[]
        def capture(*a,**kw):
            file=real_tempfile(*a,**kw);opened.append(file);return file
        with patch('src.note_export.tempfile.TemporaryFile',side_effect=capture), patch('src.note_export._write_markdown',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):build_note_export('exporter','zip')
        self.assertTrue(opened[0].closed)
        file=build_note_export('exporter','zip')
        response=NoteExportResponse(file,'zip')
        async def disconnected():
            async def receive():return {'type':'http.disconnect'}
            async def send(message):raise OSError('connection lost')
            try:await response({'type':'http','asgi':{'spec_version':'2.4'}},receive,send)
            except Exception:pass
        asyncio.run(disconnected())
        self.assertTrue(file.closed)

    def test_large_zip_bounded_memory_and_integrity(self):
        # ~64 MiB of source text, inserted in small batches before measuring.
        payload=os.urandom(32768).hex()
        with patch('src.note_indexing.enqueue_note'), SessionLocal() as db:
            for batch in range(40):
                db.bulk_insert_mappings(Note,[dict(id=f'bulk-{batch}-{i}',owner='bulk',title=f'Note {batch}-{i}',content=payload,archived=False) for i in range(25)])
            db.commit()
        def rss():
            return int(Path('/proc/self/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
        baseline=rss()
        samples=[baseline]
        stopped=threading.Event()
        def sample_memory():
            while not stopped.wait(0.01):samples.append(rss())
        sampler=threading.Thread(target=sample_memory,daemon=True)
        sampler.start()
        tracemalloc.start()
        try:
            file=build_note_export('bulk','zip')
            _,peak=tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
            stopped.set()
            sampler.join()
        growth=max(samples+[rss()])-baseline
        try:
            self.assertLess(peak,16*1024*1024, f'Peak Python allocations: {peak}')
            self.assertLess(growth,24*1024*1024, f'Peak process RSS growth: {growth}')
            with zipfile.ZipFile(file) as archive:
                self.assertEqual(len(archive.namelist()),1000)
                self.assertIsNone(archive.testzip())
            print(f'\nLarge export: 1,000 notes / 62.5 MiB body text; peak Python allocations {peak/1024/1024:.2f} MiB; process RSS growth {growth/1024/1024:.2f} MiB',flush=True)
        finally:file.close()

if __name__=='__main__':unittest.main()
