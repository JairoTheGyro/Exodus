"""Disposable mode-parity checks; no live providers, mail or notifications.
Run with the cached Exodus image and a read-only checkout, network disabled.
"""
import os
import tempfile
from pathlib import Path
import sys
_tmp = tempfile.TemporaryDirectory(prefix='exodus-mode-parity-')
ROOT = Path(_tmp.name)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.update(ODYSSEUS_DATA_DIR=str(ROOT), DATABASE_URL='sqlite:///' + str(ROOT/'app.db'),
                  PYTHON_DOTENV_DISABLED='1', AUTH_ENABLED='true', LOCALHOST_BYPASS='false',
                  EXODUS_INVITE_ONLY='true', NTFY_ENABLED='false')
import asyncio
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.auth import AuthManager
from core.database import Base, engine, SessionLocal, ScheduledTask, TaskRun, Note
from src import ai_policy as policy
from src.home_store import database, save
from src.task_scheduler import TaskScheduler
from routes.auth_routes import setup_auth_routes, SESSION_COOKIE
from routes.task_routes import setup_task_routes
from routes.note_routes import setup_note_routes, dispatch_reminder
from src import notifications

Base.metadata.create_all(engine)

class ModeParity(unittest.TestCase):
    def setUp(self):
        self.manager = AuthManager(str(ROOT/os.urandom(6).hex()/'auth.json'))
        self.manager.setup('owner', 'disposable-owner-password')
        self.scheduler = TaskScheduler(None)
        self.scheduler.ensure_defaults = AsyncMock()
        self.scheduler.run_task_now = AsyncMock(return_value=True)
        self.app = FastAPI()
        self.app.state.auth_manager = self.manager
        self.app.add_middleware(policy.WorkspacePolicyMiddleware)
        @self.app.middleware('http')
        async def identity(request, call_next):
            request.state.current_user = self.manager.get_username_for_token(request.cookies.get(SESSION_COOKIE))
            return await call_next(request)
        self.app.include_router(setup_auth_routes(self.manager))
        self.app.include_router(setup_task_routes(self.scheduler))
        self.app.include_router(setup_note_routes())
        self.client = TestClient(self.app)
        self.client.cookies.set(SESSION_COOKIE, self.manager.create_session_trusted('owner'))
        with database() as db:
            db.execute('DELETE FROM profiles')
            save('owner', {'mode':'ai-free'}, db)
        with SessionLocal() as db:
            db.query(TaskRun).delete(); db.query(ScheduledTask).delete(); db.query(Note).delete(); db.commit()
        from src.integrations import save_integrations
        save_integrations([])
        self.addCleanup(self.client.close)
        indexer = patch("src.note_indexing.enqueue_note")
        indexer.start(); self.addCleanup(indexer.stop)

    def task(self, task_id, action='tidy_documents', task_type='action', **kw):
        with SessionLocal() as db:
            task=ScheduledTask(id=task_id, owner='owner', name='Disposable test', task_type=task_type,
                action=action, status='active', output_target='none', schedule='daily', scheduled_time='09:00',
                **kw)
            db.add(task);db.commit()

    def test_explicit_allowlists_and_path_boundaries(self):
        for action in policy.NON_AI_TASK_ACTIONS:
            self.assertFalse(policy.task_uses_ai('action', action, 'none'))
        for action in ('unknown', 'run_local', 'run_script', 'ssh_command', 'cookbook_serve', 'summarize_emails'):
            self.assertTrue(policy.task_uses_ai('action', action))
        self.assertTrue(policy.task_uses_ai('llm', 'tidy_documents'))
        for target in ('mcp__custom__send', 'mcp__send@example.test', 'custom__unknown'):
            self.assertTrue(policy.task_uses_ai('action','tidy_documents',target))
        for target in ('none','notification','session','email','email:self','owner@example.test'):
            self.assertFalse(policy.task_uses_ai('action','tidy_documents',target))
        self.assertTrue(policy.allowed_without_ai('/api/notes/fire-reminder','POST'))
        self.assertTrue(policy.allowed_without_ai('/api/notes/import/json','POST'))
        self.assertFalse(policy.allowed_without_ai('/api/notes/import/json','GET'))
        self.assertFalse(policy.allowed_without_ai('/api/notes/import/anything','POST'))
        for path in ('/api/tasks/parse', '/api/tasks/x/unknown', '/api/code/bridge/v1/chat/completions'):
            self.assertFalse(policy.allowed_without_ai(path, 'POST'))

    def test_task_crud_and_manual_run_policy_both_modes(self):
        body={'task_type':'action','action':'tidy_documents','schedule':'daily','output_target':'none'}
        result=self.client.post('/api/tasks',json=body)
        self.assertEqual(result.status_code,200,result.text); task_id=result.json()['id']
        self.assertEqual(self.client.post(f'/api/tasks/{task_id}/run').status_code,200)
        self.assertEqual(self.client.put(f'/api/tasks/{task_id}',json={'action':'run_local'}).status_code,403)
        self.assertEqual(self.client.post('/api/tasks',json={'prompt':'Never send','schedule':'daily'}).status_code,403)
        self.assertEqual(self.client.post('/api/tasks/parse',json={'prompt':'Never send'}).status_code,403)
        actions={x['name'] for x in self.client.get('/api/tasks/meta/actions').json()['actions']}
        self.assertEqual(actions, policy.NON_AI_TASK_ACTIONS)
        self.assertEqual(self.client.delete(f'/api/tasks/{task_id}').status_code,200)
        with database() as db: save('owner', {'mode':'full'}, db)
        self.assertEqual(self.client.post('/api/tasks',json={**body,'name':'Existing Full workflow'}).status_code,200)
        self.assertIn('summarize_emails',{x['name'] for x in self.client.get('/api/tasks/meta/actions').json()['actions']})

    def test_ai_definition_kept_but_cannot_resume_or_run(self):
        self.task('ai',action=None,task_type='llm',prompt='No call')
        rows=self.client.get('/api/tasks').json()['tasks']
        self.assertTrue(next(x for x in rows if x['id']=='ai')['blocked_by_mode'])
        self.assertEqual(self.client.post('/api/tasks/ai/run').status_code,403)
        self.assertEqual(self.client.post('/api/tasks/ai/resume').status_code,403)
        self.assertEqual(self.client.post('/api/tasks/ai/pause').status_code,200)
        self.assertEqual(self.client.get('/api/tasks/ai').status_code,200)

    def test_scheduler_runs_maintenance_skips_model_jobs(self):
        for task_id, action, typ in [('ordinary','tidy_documents','action'),('model','summarize_emails','action'),('unknown','unreviewed','action')]:
            self.task(task_id,action,typ)
            with SessionLocal() as db:
                db.add(TaskRun(id='run-'+task_id,task_id=task_id,status='queued'));db.commit()
        async def check():
            with patch.object(self.scheduler,'_execute_action',AsyncMock(return_value=('Done',True))) as execute, patch.object(self.scheduler,'_deliver_task_result',AsyncMock()), patch.object(self.scheduler,'_log_to_assistant'):
                for task_id in ('ordinary','model','unknown'):
                    await self.scheduler._execute_task_locked(task_id,'run-'+task_id,gate_foreground=False)
                self.assertEqual(execute.await_count,1)
        asyncio.run(check())
        with SessionLocal() as db:
            self.assertEqual(db.get(TaskRun,'run-ordinary').status,'success')
            self.assertEqual(db.get(TaskRun,'run-model').status,'skipped')
            self.assertEqual(db.get(TaskRun,'run-unknown').status,'skipped')

    def test_due_scan_selects_only_ordinary_actions(self):
        self.task('ordinary',next_run=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(minutes=1))
        self.task('model',action='summarize_emails',next_run=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(minutes=1))
        async def check():
            with patch.object(self.scheduler,'_execute_task',AsyncMock()) as execute, patch('src.interactive_gate.has_foreground_activity',return_value=False):
                await self.scheduler._check_due_tasks();await asyncio.sleep(0)
                execute.assert_awaited_once_with('ordinary')
        asyncio.run(check())

    def test_action_notification_is_explicit_and_owner_scoped(self):
        for task_id, output, enabled in [('alert','notification',True),('quiet','none',True),('muted','notification',False)]:
            self.task(task_id, notifications_enabled=enabled)
            with SessionLocal() as db:
                db.get(ScheduledTask,task_id).output_target=output
                db.commit()
        async def check():
            with patch.object(self.scheduler,'_execute_action',AsyncMock(return_value=('Completed locally',True))), patch.object(self.scheduler,'_log_to_assistant'):
                for task_id in ('alert','quiet','muted'):
                    await self.scheduler._execute_task_locked(task_id,'run-'+task_id,gate_foreground=False)
        asyncio.run(check())
        self.assertEqual(self.scheduler.pop_notifications('someone-else'),[])
        alerts=self.scheduler.pop_notifications('owner')
        self.assertEqual([n['task_id'] for n in alerts],['alert'])
        self.assertEqual(alerts[0]['body'],'Completed locally')

    def test_mode_switch_does_not_cancel_maintenance(self):
        self.task('ordinary')
        entered=asyncio.Event();release=asyncio.Event()
        @policy.scheduled_owner
        async def ordinary(_self,task_id):
            self.assertEqual(policy.AI_OWNER.get(),'owner')
            entered.set();await release.wait();return 'done'
        async def check():
            task=asyncio.create_task(ordinary(self,'ordinary'));await entered.wait()
            policy.cancel_ai('owner');release.set()
            self.assertEqual(await task,'done')
        asyncio.run(check())

    def test_reminder_plain_text_survives_enabled_synthesis_without_model(self):
        async def check():
            with patch('src.settings.load_settings',return_value={'reminder_channel':'ntfy','reminder_llm_synthesis':True}), patch('src.endpoint_resolver.resolve_endpoint',side_effect=AssertionError('Do not resolve model')), patch('src.notifications.dispatch_notification',AsyncMock(return_value={'status':'sent'})) as send:
                result=await dispatch_reminder(title='Pay attention',note_body='Exact reminder text',note_id='',owner='owner',queue_browser=False)
                self.assertTrue(result['ntfy_sent']); self.assertIsNone(result['synthesis'])
                self.assertEqual(send.await_args.args[0],'Exact reminder text')
        asyncio.run(check())

    def test_full_mode_reminder_synthesis_uses_its_owner_context(self):
        with database() as db: save('owner', {'mode':'full'}, db)
        async def fake_model(*args, **kwargs):
            self.assertEqual(policy.AI_OWNER.get(),'owner')
            return 'A small reminder.'
        async def check():
            with patch('src.settings.load_settings',return_value={'reminder_channel':'ntfy','reminder_llm_synthesis':True}), patch('src.endpoint_resolver.resolve_endpoint',return_value=('http://invalid.test','test-model',{})), patch('src.llm_core.llm_call_async',side_effect=fake_model), patch('src.notifications.dispatch_notification',AsyncMock(return_value={'status':'sent'})) as send:
                result=await dispatch_reminder(title='Reminder',note_body='Body',note_id='',owner='owner',queue_browser=False)
                self.assertEqual(result['synthesis'],'A small reminder.')
                self.assertEqual(send.await_args.args[0],'A small reminder.')
                self.assertIsNone(policy.AI_OWNER.get())
        asyncio.run(check())

    def test_reminder_endpoint_is_accessible_without_ai(self):
        with SessionLocal() as db:
            db.add(Note(id='owned',owner='owner',title='Reminder',content='Body'));db.commit()
        with patch('routes.note_routes.dispatch_reminder',AsyncMock(return_value={'synthesis':None,'ntfy_sent':False})) as dispatch:
            result=self.client.post('/api/notes/fire-reminder',json={'note_id':'owned'})
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(dispatch.await_args.kwargs['owner'],'owner')
        with SessionLocal() as db:
            db.add(Note(id='foreign',owner='someone-else',title='Private'));db.commit()
        self.assertEqual(self.client.post('/api/notes/fire-reminder',json={'note_id':'foreign'}).status_code,404)

    def test_supported_integrations_save_test_and_reject_unknown(self):
        body={'preset':'gitea','name':'Local git','base_url':'http://example.test'}
        result=self.client.post('/api/auth/integrations',json=body)
        self.assertEqual(result.status_code,200,result.text); iid=result.json()['integration']['id']
        self.assertEqual(self.client.put('/api/auth/integrations/'+iid,json={'name':'Edited'}).status_code,200)
        with patch('routes.auth_routes.execute_api_call',AsyncMock(return_value={'exit_code':0})) as probe:
            self.assertTrue(self.client.post('/api/auth/integrations/'+iid+'/test').json()['ok'])
            probe.assert_awaited_once_with(iid,'GET','/api/v1/version')
        self.assertEqual(self.client.put('/api/auth/integrations/'+iid,json={'preset':'unknown-ai'}).status_code,403)
        self.assertEqual(self.client.post('/api/auth/integrations',json={**body,'preset':'custom'}).status_code,403)
        with patch.object(self.manager,'is_admin',return_value=False):
            self.assertEqual(self.client.post('/api/auth/integrations',json=body).status_code,403)
        self.assertEqual(self.client.delete('/api/auth/integrations/'+iid).status_code,200)
        with database() as db: save('owner', {'mode':'full'}, db)
        self.assertEqual(self.client.post('/api/auth/integrations',json={**body,'preset':'custom'}).status_code,200)

    def test_ntfy_native_fallback_and_explicit_disable(self):
        with patch.dict(os.environ,{},clear=True),patch('src.integrations.load_integrations',return_value=[]):
            self.assertEqual(notifications._destination(),('http://localhost:8091',''))
        with patch('src.integrations.load_integrations',return_value=[{'preset':'ntfy','enabled':False,'base_url':'http://ntfy'}]):
            self.assertIsNone(notifications._destination())

if __name__=='__main__':unittest.main(verbosity=2)
