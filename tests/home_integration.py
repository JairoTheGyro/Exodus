"""Disposable Home + account-policy tests. No real models or user data.
Run: docker exec -i sovereign-hub-odysseus-1 python - < tests/home_integration.py
"""
import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

_temp = tempfile.TemporaryDirectory(prefix='exodus-home-tests-')
os.environ['ODYSSEUS_DATA_DIR'] = _temp.name
os.environ['DATABASE_URL'] = 'sqlite:///' + _temp.name + '/test.db'
os.environ['AUTH_ENABLED'] = 'true'
os.environ['LOCALHOST_BYPASS'] = 'false'

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from core.database import Base, engine, SessionLocal, Note, Document
from src.home_store import database, profile, save
from src.ai_policy import WorkspacePolicyMiddleware, AI_OWNER, require_ai, tracked_ai, cancel_ai, _active, allowed_without_ai
from routes.home_routes import setup_home_routes
Base.metadata.create_all(engine)
app = FastAPI()
app.state.auth_manager = SimpleNamespace(is_configured=True, is_admin=lambda u:u=='admin',get_privileges=lambda u:{'can_use_documents':u!='blocked'})
app.add_middleware(WorkspacePolicyMiddleware)
@app.middleware('http')
async def identity(request, call_next):
    request.state.current_user = request.headers.get('x-test-user')
    return await call_next(request)
app.include_router(setup_home_routes())
@app.post('/api/chat')
async def chat(): return {'reached':True}

class HomeChecks(unittest.TestCase):
    def setUp(self):
        self.c=TestClient(app);self.c.headers['x-test-user']='admin'
        with database() as db:
            db.execute('DELETE FROM profiles');db.execute('DELETE FROM activity')
        with SessionLocal() as db:
            db.query(Note).delete();db.query(Document).delete();db.commit()
    def test_mode_is_owner_scoped_and_switchable(self):
        self.assertEqual(self.c.patch('/api/home/profile',json={'mode':'ai-free'}).status_code,200)
        self.assertEqual(self.c.post('/api/chat').status_code,403)
        self.c.headers['x-test-user']='other'
        self.assertEqual(self.c.post('/api/chat').status_code,200)
        self.assertNotIn('mode',self.c.get('/api/home/profile').json()['profile'])
        self.c.headers['x-test-user']='admin'
        self.assertEqual(self.c.patch('/api/home/profile',json={'mode':'full'}).status_code,200)
        self.assertEqual(self.c.post('/api/chat').status_code,200)
    def test_non_ai_surface_and_direct_bypasses(self):
        for path in ['/api/chat','/api/workshop/generate','/api/code/bridge/v1/chat/completions','/api/tts','/api/stt','/api/image/generate','/api/email/summarize','/api/email/ai-reply','/api/email/auto-summarize-now','/api/documents/ai-tidy','/api/document/abc/ai-fill-annotations','/api/future-ai','/v1/chat/completions','/ws/agent']:
            self.assertFalse(allowed_without_ai(path,'POST'),path)
        self.assertTrue(allowed_without_ai('/api/calendar/quick-parse','POST'))
        for path in ['/api/home/profile','/api/notes','/api/notes/123/items/0/toggle','/api/calendar/events','/api/email/send','/api/email/search','/api/document/123','/api/document/123/export-pdf','/api/documents/library']:
            self.assertTrue(allowed_without_ai(path,'GET'),path)
    def test_tasks_reuse_notes_and_reject_stale_or_foreign_edits(self):
        r=self.c.post('/api/home/tasks',json={'text':'QA checklist','project':'QA','due':'2026-09-29','priority':'high'})
        self.assertEqual(r.status_code,200,r.text); nid=r.json()['note_id']
        rows=self.c.get('/api/home/tasks').json()['tasks'];self.assertEqual(rows[0]['priority'],'high')
        self.assertEqual(self.c.put(f'/api/home/tasks/{nid}/0',json={'text':'wrong','done':True}).status_code,409)
        self.assertEqual(self.c.put(f'/api/home/tasks/{nid}/0',json={'text':'QA checklist','done':True}).status_code,200)
        with SessionLocal() as db:self.assertIn('true',db.get(Note,nid).items)
        self.c.headers['x-test-user']='other'
        self.assertEqual(self.c.get('/api/home/tasks').json()['tasks'],[])
        self.assertEqual(self.c.put(f'/api/home/tasks/{nid}/0',json={'text':'QA checklist','done':False}).status_code,404)
    def test_capture_files_search_and_permissions(self):
        self.c.post('/api/home/capture',json={'text':'Findme <script>never executed</script>'})
        with SessionLocal() as db:
            db.add_all([Document(id='mine',owner='admin',title='Findme mine',current_content=''),Document(id='foreign',owner='other',title='Findme foreign',current_content='')]);db.commit()
        self.assertEqual([f['id'] for f in self.c.get('/api/home/files').json()['files']],['mine'])
        self.assertEqual(len(self.c.get('/api/home/search?q=Findme').json()['results']),2)
        self.assertEqual(self.c.get('/api/home/search?q=%25%25').json()['results'],[])
        self.c.headers['x-test-user']='blocked'
        self.assertEqual(self.c.get('/api/home/files').status_code,403)
        self.assertEqual(self.c.get('/api/home/search?q=Findme').json()['results'],[])
    def test_recent_email_subjects_in_both_modes(self):
        with SessionLocal() as db:
            db.add_all([
                Document(id='email',owner='admin',title='New Email',language='email',current_content='To: test@example.test\nSubject: Test\n---\nBody'),
                Document(id='blank',owner='admin',title='Email',language='email',current_content='To: test@example.test\nSubject: \n---\nSubject: NOT the envelope'),
                Document(id='folded',owner='admin',title='New Email',language='email',current_content='To: test@example.test\r\nSubject: Actual\r\n subject <&>\r\n---\r\nBody'),
                Document(id='ordinary',owner='admin',title='Email',language='markdown',current_content='Subject: not email metadata'),
                Document(id='foreign-email',owner='other',title='Private subject',language='email',current_content='Subject: Secret'),
            ]);db.commit()
        for mode in ('full','ai-free'):
            self.c.patch('/api/home/profile',json={'mode':mode,'pins':['email','foreign-email']})
            rows={r['id']:r for r in self.c.get('/api/home/files').json()['files']}
            self.assertEqual(rows['email']['title'],'Test')
            self.assertTrue(rows['email']['pinned'])
            self.assertEqual(rows['blank']['title'],'(No Subject)')
            self.assertEqual(rows['folded']['title'],'Actual subject <&>')
            self.assertEqual(rows['ordinary']['title'],'Email')
            self.assertNotIn('foreign-email',rows)
        with SessionLocal() as db:
            doc=db.get(Document,'email');doc.current_content='To: example@example.test\nSubject: Edited subject\n---\n';db.commit()
        self.assertEqual(next(r['title'] for r in self.c.get('/api/home/files').json()['files'] if r['id']=='email'),'Edited subject')

    def test_timer_conflict_cap_and_persistence(self):
        with patch('routes.home_routes.time.time',return_value=1000):
            self.assertEqual(self.c.post('/api/home/focus',json={'action':'start','minutes':1}).status_code,200)
        self.assertEqual(self.c.post('/api/home/focus',json={'action':'start'}).status_code,409)
        self.assertEqual(self.c.get('/api/home/focus').json()['active']['started'],1000)
        with patch('routes.home_routes.time.time',return_value=1150):
            r=self.c.post('/api/home/focus',json={'action':'stop'}).json()
            self.assertEqual(r['sessions'][0]['seconds'],60);self.assertIsNone(r['active'])
        self.assertEqual(self.c.post('/api/home/focus',json={'action':'stop'}).status_code,409)
    def test_team_opt_in_and_personal_layout(self):
        self.c.patch('/api/home/profile',json={'status':'focus','order':['focus','tasks'],'hidden':['team']})
        self.assertEqual(self.c.get('/api/home/team').json()['people'],[])
        self.c.patch('/api/home/profile',json={'share_presence':True})
        self.c.post('/api/home/presence')
        self.c.post('/api/home/announcements',json={'body':'Explicit disposable announcement'})
        self.c.headers['x-test-user']='other'
        team=self.c.get('/api/home/team').json();self.assertTrue(team['people'][0]['online']);self.assertEqual(team['activity'][0]['owner'],'admin')
        self.assertNotIn('hidden',self.c.get('/api/home/profile').json()['profile'])
        self.assertEqual(self.c.patch('/api/home/profile',json={'order':['unknown']}).status_code,422)
    def test_goals_links_and_offline_weather(self):
        self.assertEqual(self.c.post('/api/home/goals',json={'title':'QA','current':2,'target':5}).status_code,200)
        self.assertEqual(self.c.post('/api/home/goals',json={'id':'foreign','title':'QA','current':2,'target':5}).status_code,404)
        self.assertEqual(self.c.post('/api/home/goals',json={'title':'QA','current':2,'target':0}).status_code,422)
        for url in ['javascript:alert(1)','https://user:password@example.com']:
            self.assertEqual(self.c.post('/api/home/shortcuts',json={'title':'QA','url':url}).status_code,422)
        self.assertEqual(self.c.post('/api/home/shortcuts',json={'title':'QA','url':'http://localhost:8080'}).status_code,200)
        with patch('routes.home_routes.httpx.AsyncClient',side_effect=AssertionError('Network must stay off')):
            self.assertEqual(self.c.get('/api/home/weather').json(),{'configured':False})
    def test_background_email_and_scheduled_jobs_stop_for_owner(self):
        from core.database import ScheduledTask, TaskRun
        from src.task_scheduler import TaskScheduler
        from routes.email_pollers import _scan_email_account
        with database() as db:save('admin',{'mode':'ai-free'},db)
        with SessionLocal() as db:
            db.add(ScheduledTask(id='background-qa',owner='admin',status='active',name='QA'))
            db.add(TaskRun(id='run-qa',task_id='background-qa',status='queued'));db.commit()
        async def check():
            with patch('routes.email_pollers._owner_for_email_account',return_value='admin'), patch('routes.email_pollers._load_settings',side_effect=AssertionError('AI pass must stop before reading provider configuration')):
                # AI scans still stop before configuration access; opted-in template
                # replies have their own mode-independent regression coverage.
                self.assertIn('disabled',await _scan_email_account(account_id='qa', away_only=False))
            scheduler=TaskScheduler(None)
            await scheduler._execute_task_locked('background-qa','run-qa')
        asyncio.run(check())
        with SessionLocal() as db:self.assertEqual(db.get(TaskRun,'run-qa').status,'skipped')

    def test_shared_inference_guard_and_nested_cancellation(self):
        async def check():
            token=AI_OWNER.set('admin')
            try:
                with database() as db:save('admin',{'mode':'ai-free'},db)
                with self.assertRaises(HTTPException): require_ai()
                # Actual common model function must fail before making a connection.
                from src.llm_core import llm_call_async
                with self.assertRaises(HTTPException): await llm_call_async('http://invalid.invalid','model',[])
                with database() as db:save('admin',{'mode':'full'},db)
                entered=asyncio.Event()
                @tracked_ai
                async def inner(): return 'done'
                @tracked_ai
                async def outer():
                    await inner();entered.set();await asyncio.Event().wait()
                task=asyncio.create_task(outer());await entered.wait()
                self.assertIn(task,_active['admin']);cancel_ai('admin')
                with self.assertRaises(asyncio.CancelledError): await task
                self.assertNotIn('admin',_active)
            finally:AI_OWNER.reset(token)
        asyncio.run(check())

if __name__=='__main__':unittest.main(verbosity=2)
