"""Isolated HTTP integration: docker exec -i sovereign-hub-odysseus-1 python - < tests/chroma_integration.py
Uses cached local embeddings, disposable owned text and a temporary Chroma collection.
"""
import asyncio, os, socket, tempfile, threading, time, unittest, uuid
from types import SimpleNamespace
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

root = tempfile.TemporaryDirectory(prefix='chroma-check-')
os.environ['FASTEMBED_CACHE_PATH'] = '/app/data/fastembed_cache'
os.environ['ODYSSEUS_DATA_DIR'] = root.name
os.environ['DATABASE_URL'] = 'sqlite:///' + root.name + '/check.db'
os.environ['AUTH_ENABLED'] = 'true'
os.environ['LOCALHOST_BYPASS'] = 'false'
from src import chroma_client as cc
from src.chat_processor import ChatProcessor
from src.embedding_lanes import collection_name
from src.rag_vector import VectorRAG
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.database import Base, engine, SessionLocal, Note
from routes import personal_routes
from src.ai_policy import WorkspacePolicyMiddleware
from src.home_store import save, database
Base.metadata.create_all(engine)

class ChromaChecks(unittest.TestCase):
    def test_environment_and_transport(self):
        cc.reset_client()
        c=cc.get_chroma_client()
        self.assertEqual(c._server._session.timeout.connect,5)
        self.assertEqual(c._server._session.timeout.read,5)
        self.assertEqual(collection_name('odysseus_rag','fastembed'),'exodus_knowledge')
        with patch.dict(os.environ, {'CHROMA_COLLECTION':'custom_knowledge'}):
            self.assertEqual(collection_name('odysseus_rag','fastembed'),'custom_knowledge')
        self.assertEqual(collection_name('odysseus_memories','fastembed'),'odysseus_memories_fastembed')

    def test_http_blackhole_times_out(self):
        release=threading.Event()
        class Silent(BaseHTTPRequestHandler):
            def do_GET(self): release.wait(10)
            def log_message(self,*args): pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Silent)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            cc.reset_client()
            with patch.dict(os.environ, {'CHROMA_HOST':'127.0.0.1','CHROMA_PORT':str(server.server_port)}):
                start=time.monotonic()
                with self.assertRaises(Exception): cc.get_chroma_client()
                self.assertLess(time.monotonic()-start,7)
                self.assertGreater(time.monotonic()-start,4.5)
                self.assertIsNone(cc._client)
        finally:
            release.set();server.shutdown();server.server_close();cc.reset_client()

    def test_offline_chat_continues(self):
        rag=SimpleNamespace(search=lambda *a,**k: (_ for _ in ()).throw(ConnectionError('offline')))
        processor=ChatProcessor(None,SimpleNamespace(rag_manager=rag))
        preface,sources,web=processor.build_context_preface('hello',None,use_memory=False,owner='alice',use_skills=False)
        self.assertTrue(preface);self.assertEqual(sources,[])

    def test_incognito_skips_knowledge(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("Incognito must not query knowledge")
        from unittest.mock import Mock
        rag=SimpleNamespace(search=Mock(side_effect=forbidden))
        processor=ChatProcessor(None,SimpleNamespace(rag_manager=rag))
        processor.build_context_preface('private question',None,use_memory=False,incognito=True)
        rag.search.assert_not_called()

    def test_live_ingestion_owner_isolation_and_chat(self):
        name='exodus_test_'+uuid.uuid4().hex
        c=cc.get_chroma_client()
        try:
            with patch.dict(os.environ, {'CHROMA_COLLECTION':name}), patch('src.embedding_lanes._build_custom_client',return_value=None):
                rag=VectorRAG(root.name)
            self.assertTrue(rag.healthy)
            self.assertEqual(rag.collection.name,name)
            app=FastAPI()
            app.state.auth_manager=SimpleNamespace(is_configured=True,is_admin=lambda u:False,get_privileges=lambda u:{'can_use_documents':True})
            app.add_middleware(WorkspacePolicyMiddleware)
            @app.middleware('http')
            async def identity(request,call_next):
                request.state.current_user=request.headers.get('x-test-user')
                return await call_next(request)
            docs=SimpleNamespace(rag_manager=rag)
            app.include_router(personal_routes.setup_personal_routes(docs,rag,True))
            client=TestClient(app);client.headers['x-test-user']='alice'
            with patch.object(personal_routes,'get_rag_manager',return_value=rag), patch('src.rag_singleton.get_rag_manager', return_value=rag):
                res=client.post('/api/personal/text',json={'text':'The garden greenhouse irrigation timer runs every morning at seven.','title':'Garden instructions'})
                self.assertEqual(res.status_code,200,res.text)
                self.assertGreater(res.json()['indexed_count'],0)
                with SessionLocal() as db:
                    db.add(Note(id='chroma-note',owner='alice',title='Orchard',content='The orchard apple trees need watering on Tuesday.',note_type='note'));db.commit()
                deadline=time.monotonic()+10
                while rag.collection.count()<2 and time.monotonic()<deadline: time.sleep(0.1)
                self.assertEqual(rag.collection.count(),2)  # Real background hook indexed without an ingestion request.
                self.assertEqual(client.post('/api/personal/text',json={'note_id':'chroma-note'}).status_code,200)
                self.assertEqual(rag.collection.count(),2)  # Manual reindex is idempotent.
                client.headers['x-test-user']='bob'
                self.assertEqual(client.post('/api/personal/text',json={'note_id':'chroma-note'}).status_code,404)
                client.headers['x-test-user']='alice'
                with database() as db: save('alice',{'mode':'ai-free'},db)
                self.assertEqual(client.post('/api/personal/text',json={'text':'blocked'}).status_code,403)
                with database() as db: save('alice',{'mode':'full'},db)
            hits=rag.search('When should I water the greenhouse?',owner='alice')
            self.assertTrue(hits)
            self.assertEqual(rag.search('greenhouse watering',owner='bob'),[])
            processor=ChatProcessor(None,docs)
            preface,sources,_=processor.build_context_preface('When should I water the greenhouse?',None,use_memory=False,owner='alice',use_skills=False)
            self.assertTrue(sources)
            self.assertTrue(any('irrigation' in row['content'] for row in preface))
            self.assertEqual(c.get_collection(name).count(),2)
        finally:
            try: c.delete_collection(name)
            except Exception: pass

if __name__=='__main__': unittest.main()
