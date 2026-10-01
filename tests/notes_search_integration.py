"""Offline Notes search checks; isolated database and no user's data.
Run inside Exodus: python - < tests/notes_search_integration.py
"""
import os, tempfile, unittest, socket
from types import SimpleNamespace
from unittest.mock import patch
_temp = tempfile.TemporaryDirectory(prefix='exodus-note-search-')
os.environ['ODYSSEUS_DATA_DIR'] = _temp.name
os.environ['DATABASE_URL'] = 'sqlite:///' + _temp.name + '/test.db'
os.environ['AUTH_ENABLED'] = 'true'
os.environ['LOCALHOST_BYPASS'] = 'false'
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.database import SessionLocal, Note
from routes.note.note_routes import setup_note_routes
from src.ai_policy import WorkspacePolicyMiddleware
from src.home_store import database, save
app=FastAPI()
app.state.auth_manager=SimpleNamespace(is_configured=True)
app.add_middleware(WorkspacePolicyMiddleware)
@app.middleware('http')
async def identity(request, call_next):
    request.state.current_user=request.headers.get('x-test-user')
    return await call_next(request)
app.include_router(setup_note_routes())
with database() as db: save('search-test', {'mode':'ai-free'}, db)
with patch('src.note_indexing.enqueue_note'), SessionLocal() as db:
    db.add_all([
        Note(id='body',owner='search-test',title='Garden plan',content='The secret ingredient is CARDAMOM. Use 100% of batch_A.'),
        Note(id='title',owner='search-test',title='Cardamom shopping',content=None),
        Note(id='checklist',owner='search-test',title='Packing',note_type='checklist',items='[{"text":"Saffron","done":false}]'),
        Note(id='foreign',owner='someone-else',title='Cardamom private',content='CARDAMOM'),
        Note(id='archived',owner='search-test',title='Old cardamom',archived=True),
    ]);db.commit()

class SearchChecks(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app);self.client.headers['x-test-user']='search-test'
    def ids(self,**params):
        # HTTP uses in-process transport; any attempted network access fails.
        with patch.object(socket.socket,'connect',side_effect=AssertionError('Search must remain offline')), patch('src.ai_policy.require_ai',side_effect=AssertionError('Search must not invoke AI')):
            result=self.client.get('/api/notes',params=params)
        self.assertEqual(result.status_code,200,result.text)
        return {n['id'] for n in result.json()['notes']}
    def test_body_only_case_insensitive(self):
        self.assertEqual(self.ids(q='SECRET INGREDIENT'),{'body'})
    def test_title_and_body(self):
        self.assertEqual(self.ids(q='cArDaMoM'),{'body','title'})
    def test_empty_and_clear_restore_notes_and_checklists(self):
        for q in ['', '  ']: self.assertEqual(self.ids(q=q),{'body','title','checklist'})
    def test_no_results(self): self.assertEqual(self.ids(q='not-present'),set())
    def test_literal_wildcards(self):
        self.assertEqual(self.ids(q='%'),{'body'})
        self.assertEqual(self.ids(q='_'),{'body'})
        self.assertEqual(self.ids(q="' OR 1=1 --"),set())
    def test_archive_and_labels_still_apply(self):
        self.assertEqual(self.ids(q='cardamom',archived='true'),{'archived'})
        self.assertEqual(self.ids(q='cardamom',label='missing'),set())
    def test_missing_identity_fails_closed(self):
        self.client.headers.pop('x-test-user')
        self.assertEqual(self.client.get('/api/notes?q=cardamom').status_code,401)

if __name__=='__main__': unittest.main()
