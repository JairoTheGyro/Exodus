"""Isolated local Library file tests: no real user data or network access."""
import io
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
_temp=tempfile.TemporaryDirectory(prefix='exodus-files-test-')
os.environ.update(ODYSSEUS_DATA_DIR=_temp.name,DATABASE_URL='sqlite:///'+_temp.name+'/test.db',
                  EXODUS_DOCUMENTS_DIR=_temp.name+'/documents',AUTH_ENABLED='true',LOCALHOST_BYPASS='false')
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from core.database import SessionLocal, DocumentFile, Document
from routes.document.document_routes import setup_document_routes
from src.ai_policy import WorkspacePolicyMiddleware, allowed_without_ai
from src.home_store import database,save
from routes import local_document_routes as files
app=FastAPI()
app.state.auth_manager=SimpleNamespace(is_configured=True,get_privileges=lambda user:{'can_use_documents':user!='blocked'})
app.add_middleware(WorkspacePolicyMiddleware)
@app.middleware('http')
async def identity(request,call_next):
    request.state.current_user=request.headers.get('x-test-user')
    return await call_next(request)
app.include_router(setup_document_routes(None))

class LibraryFileChecks(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app,raise_server_exceptions=False)
        self.client.headers['x-test-user']='alice'
        with database() as db:save('alice',{'mode':'ai-free'},db)
        with SessionLocal() as db:
            db.query(DocumentFile).delete();db.commit()
        for path in files._root().iterdir():path.unlink()
    def upload(self,name='example.md',data=b'# Local only\nTest file',mime='text/markdown'):
        with patch.object(socket.socket,'connect',side_effect=AssertionError('No network')),patch('src.ai_policy.require_ai',side_effect=AssertionError('No AI')):
            return self.client.post('/api/documents/upload',files={'file':(name,data,mime)})
    def test_roundtrip_formats_modes_metadata_and_restart(self):
        for mode in ['ai-free','full']:
            with database() as db:save('alice',{'mode':mode},db)
            for ext,mime in files.FORMATS.items():
                payload=b'original bytes\x00\xff\n'
                response=self.upload('sample'+ext,payload,'application/octet-stream')
                self.assertEqual(response.status_code,201,response.text)
                row=response.json();self.assertEqual(row['file_size'],len(payload));self.assertEqual(row['mime_type'],mime)
                self.assertTrue(row['created_at'])
                with SessionLocal() as db:
                    stored=db.get(DocumentFile,row['id'])
                    self.assertEqual(files._path(stored.storage_name).read_bytes(),payload)
                download=self.client.get('/api/documents/'+row['id']+'/download')
                self.assertEqual(download.status_code,200);self.assertEqual(download.content,payload)
                self.assertTrue(download.headers['content-disposition'].startswith('attachment;'))
                self.assertEqual(download.headers['x-content-type-options'],'nosniff')
        # New connection/client reads the persisted registry, not process memory.
        fresh=TestClient(app);fresh.headers['x-test-user']='alice'
        listed=fresh.get('/api/documents').json()
        self.assertEqual(listed['total'],len(files.FORMATS)*2)
        self.assertEqual(len(fresh.get('/api/documents?limit=1&offset=1').json()['files']),1)
    def test_duplicate_and_path_names_cannot_overwrite_or_escape(self):
        names=['../../report.txt',r'C:\Users\sample.txt','.hidden.txt','résumé.txt','report.txt','report.txt']
        ids=[]
        for name in names:
            result=self.upload(name)
            self.assertEqual(result.status_code,201,result.text)
            row=result.json();ids.append(row['id'])
            self.assertNotIn('/',row['filename']);self.assertNotIn('\\',row['filename'])
        self.assertEqual(len(set(ids)),len(names))
        self.assertEqual(len(list(files._root().iterdir())),len(names))
        with self.assertRaises(Exception):files._path('../../outside')
    def test_owner_and_privilege_isolation_all_operations(self):
        id=self.upload().json()['id']
        for user,status in [('bob',404),('blocked',403)]:
            self.client.headers['x-test-user']=user
            self.assertEqual(self.client.get(f'/api/documents/{id}/download').status_code,status)
            self.assertEqual(self.client.delete(f'/api/documents/{id}').status_code,status)
        self.assertEqual(self.upload().status_code,403)
        self.client.headers['x-test-user']='bob'
        self.assertEqual(self.client.get('/api/documents').json()['files'],[])
        self.client.headers.pop('x-test-user')
        self.assertEqual(self.upload().status_code,401)
        self.assertEqual(self.client.get('/api/documents').status_code,401)
        self.assertEqual(self.client.get(f'/api/documents/{id}/download').status_code,401)
    def test_invalid_empty_oversized_and_chunked_uploads_clean_up(self):
        self.assertEqual(self.upload('program.exe').status_code,415)
        self.assertEqual(self.upload(data=b'').status_code,400)
        with patch.object(files,'DOCUMENT_UPLOAD_MAX_BYTES',1024):
            self.assertEqual(self.upload(data=b'x'*1025).status_code,413)
            self.assertEqual(self.upload(data=b'x'*100000).status_code,413)
            boundary='TESTBOUNDARY'
            def body():
                yield f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="test.txt"\r\n\r\n'.encode()
                for _ in range(30):yield b'x'*4096
                yield f'\r\n--{boundary}--\r\n'.encode()
            response=self.client.post('/api/documents/upload',content=body(),headers={'Content-Type':'multipart/form-data; boundary='+boundary})
            self.assertEqual(response.status_code,413,response.text)
        self.assertEqual(list(files._root().iterdir()),[])
        self.assertEqual(self.client.get('/api/documents').json()['total'],0)
    def test_delete_removes_both_and_missing_disk_file_can_be_removed(self):
        for missing in [False,True]:
            id=self.upload().json()['id']
            with SessionLocal() as db:path=files._path(db.get(DocumentFile,id).storage_name)
            if missing:path.unlink()
            result=self.client.delete('/api/documents/'+id)
            self.assertEqual(result.status_code,200,result.text)
            self.assertFalse(path.exists())
            self.assertEqual(self.client.get('/api/documents').json()['total'],0)
            self.assertEqual(self.client.get('/api/documents/'+id+'/download').status_code,404)
    def test_failed_delete_is_visible_and_retryable(self):
        id=self.upload().json()['id']
        with patch.object(Path,'unlink',side_effect=PermissionError('read-only')):
            self.assertEqual(self.client.delete('/api/documents/'+id).status_code,503)
        self.assertTrue(self.client.get('/api/documents').json()['files'][0]['deletion_pending'])
        self.assertEqual(self.client.get(f'/api/documents/{id}/download').status_code,409)
        self.assertEqual(self.client.delete('/api/documents/'+id).status_code,200)
        self.assertEqual(list(files._root().iterdir()),[])
    def test_failed_registry_commit_removes_partial_upload(self):
        with patch.object(Session,'commit',side_effect=RuntimeError('DB unavailable')):
            self.assertEqual(self.upload().status_code,500)
        self.assertEqual(list(files._root().iterdir()),[])
        self.assertEqual(self.client.get('/api/documents').json()['total'],0)
    def test_symlink_target_is_not_read_or_deleted(self):
        row=self.upload().json()
        with SessionLocal() as db:path=files._path(db.get(DocumentFile,row['id']).storage_name)
        target=Path(_temp.name)/'outside.txt';target.write_text('private outside bytes')
        path.unlink();path.symlink_to(target)
        self.assertEqual(self.client.get('/api/documents/'+row['id']+'/download').status_code,409)
        self.assertEqual(self.client.delete('/api/documents/'+row['id']).status_code,409)
        self.assertEqual(target.read_text(),'private outside bytes')
    def test_existing_editable_documents_unchanged(self):
        response=self.client.post('/api/document',json={'title':'Editable','content':'Retained','language':'markdown'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.client.get('/api/documents').json()['files'],[])
        library=self.client.get('/api/documents/library')
        self.assertEqual(library.status_code,200)
        self.assertIn('Editable',library.text)
        self.assertFalse(allowed_without_ai('/api/documents/ai-tidy','POST'))

if __name__=='__main__':unittest.main()
