"""Local tags/archive API and indexing checks using disposable Notes state.
Run with tests on PYTHONPATH inside Exodus: python tests/notes_organization_integration.py
"""
import json, unittest, uuid
from types import SimpleNamespace
from unittest.mock import patch
from notes_search_integration import app, SessionLocal, Note, database, save, socket
from fastapi.testclient import TestClient
from src import note_indexing as ni

class OrganizationChecks(unittest.TestCase):
    def setUp(self):
        self.c=TestClient(app); self.c.headers['x-test-user']='search-test'
        self.jobs=[]
        self.hook=patch.object(ni,'enqueue_note',side_effect=lambda *args:self.jobs.append(args));self.hook.start()
        self.network=patch.object(socket.socket,'connect',side_effect=AssertionError('Must stay offline'));self.network.start()
    def tearDown(self):
        self.network.stop();self.hook.stop()
        with database() as db: save('search-test',{'mode':'ai-free'},db)
    def create(self,**fields):
        r=self.c.post('/api/notes',json={'title':'Organization QA '+uuid.uuid4().hex,'content':'Private local note',**fields})
        self.assertEqual(r.status_code,200,r.text);return r.json()
    def update(self,nid,**fields):
        r=self.c.put('/api/notes/'+nid,json=fields);self.assertEqual(r.status_code,200,r.text);return r.json()
    def test_tags_persist_and_legacy_labels_interoperate(self):
        note=self.create(tags=['#Work','Personal','Work'])
        self.assertEqual(note['tags'],['Work','Personal']);self.assertFalse(note['is_archived'])
        with SessionLocal() as db:
            stored=db.get(Note,note['id']);self.assertEqual(stored.tags,['Work','Personal']);self.assertEqual(stored.label,'Work Personal')
        changed=self.update(note['id'],label='Family travel')
        self.assertEqual(changed['tags'],['Family','travel'])
        self.assertEqual(self.update(note['id'],tags=[])['tags'],[])
        self.assertEqual(len(self.jobs),3)
    def test_archive_unarchive_and_owner_protection(self):
        note=self.create(tags=['Work']);nid=note['id']
        self.assertTrue(self.update(nid,is_archived=True)['archived'])
        self.assertNotIn(nid,{n['id'] for n in self.c.get('/api/notes').json()['notes']})
        archived=self.c.get('/api/notes?is_archived=true').json()['notes']
        self.assertIn(nid,{n['id'] for n in archived})
        self.c.headers['x-test-user']='someone-else'
        self.assertEqual(self.c.put('/api/notes/'+nid,json={'is_archived':False}).status_code,404)
        self.c.headers['x-test-user']='search-test'
        self.assertFalse(self.update(nid,is_archived=False)['archived'])
        self.assertIn(nid,{n['id'] for n in self.c.get('/api/notes').json()['notes']})
        self.assertEqual(len(self.jobs),3)
    def test_legacy_archive_toggle_and_conflicts(self):
        note=self.create(archived=True)
        self.assertTrue(note['is_archived'])
        r=self.c.post('/api/notes/'+note['id']+'/archive').json()
        self.assertFalse(r['is_archived']);self.assertFalse(r['archived'])
        self.assertEqual(self.c.put('/api/notes/'+note['id'],json={'archived':True,'is_archived':False}).status_code,422)
        self.assertEqual(self.c.get('/api/notes?archived=true&is_archived=false').status_code,400)
    def test_invalid_tags_rejected(self):
        for tags in [['multi word'], ['a'*101], [str(i) for i in range(51)]]:
            self.assertEqual(self.c.post('/api/notes',json={'tags':tags}).status_code,422)
    def test_sync_metadata_and_ai_free_deferral(self):
        note=self.create(tags=['Work']);nid=note['id'];rows={}
        class Collection:
            def get(self,**kwargs): return {'ids':list(rows)}
            def upsert(self,ids,documents,embeddings,metadatas):
                rows.update({i:m for i,m in zip(ids,metadatas)})
            def delete(self,ids):
                for i in ids: rows.pop(i,None)
        from unittest.mock import Mock
        encode=Mock(return_value=[[1.,2.]])
        rag=SimpleNamespace(healthy=True,_lanes=[SimpleNamespace(collection=Collection(),encode=encode)],_split_into_chunks=lambda text,chunk_size:[text])
        self.assertEqual(ni.ingest_note(nid,'search-test',rag=rag)['status'],'unavailable');encode.assert_not_called()
        with database() as db:save('search-test',{'mode':'full'},db)
        self.assertEqual(ni.ingest_note(nid,'search-test',rag=rag)['status'],'indexed')
        old=next(iter(rows.values()));self.assertEqual(json.loads(old['tags']),['Work']);self.assertTrue(ni.current_metadata(old))
        self.update(nid,tags=['Personal'],is_archived=True)
        self.assertFalse(ni.current_metadata(old))
        self.assertEqual(ni.ingest_note(nid,'search-test',rag=rag)['status'],'indexed')
        current=next(iter(rows.values()));self.assertEqual(json.loads(current['tags']),['Personal']);self.assertTrue(current['is_archived'])
        self.assertTrue(ni.current_metadata(current));self.assertEqual(len(rows),1)
        self.assertEqual(len(self.jobs),2)

if __name__=='__main__':unittest.main()
