"""Isolated invitation/auth, preferences and vault account regression tests.
Run standalone in the installed image; never read live runtime data or providers.
"""
import os
import tempfile
from pathlib import Path
import sys
_tmp = tempfile.TemporaryDirectory(prefix='exodus-team-tests-')
ROOT = Path(_tmp.name)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.update(ODYSSEUS_DATA_DIR=str(ROOT), DATABASE_URL='sqlite:///' + str(ROOT / 'app.db'),
                  PYTHON_DOTENV_DISABLED='1', AUTH_ENABLED='true', LOCALHOST_BYPASS='false',
                  EXODUS_INVITE_ONLY='true', NTFY_ENABLED='false')
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.auth import AuthManager
from core.database import Base, engine
from routes.auth_routes import setup_auth_routes, SESSION_COOKIE
from routes.prefs_routes import setup_prefs_routes
from routes.home_routes import setup_home_routes
from routes.vault.vault_routes import setup_vault_routes, _run_bw
from routes.vaultwarden_routes import setup_vaultwarden_routes
from src import vault_accounts
from src.ai_policy import WorkspacePolicyMiddleware

Base.metadata.create_all(engine)


def make_app(manager):
    app = FastAPI()
    app.state.auth_manager = manager
    app.add_middleware(WorkspacePolicyMiddleware)
    @app.middleware('http')
    async def identity(request, call_next):
        request.state.current_user = manager.get_username_for_token(request.cookies.get(SESSION_COOKIE))
        return await call_next(request)
    app.include_router(setup_auth_routes(manager))
    app.include_router(setup_prefs_routes())
    app.include_router(setup_home_routes())
    app.include_router(setup_vault_routes())
    app.include_router(setup_vaultwarden_routes())
    return app


class TeamChecks(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / os.urandom(6).hex() / 'auth.json'
        self.manager = AuthManager(str(self.path))
        self.manager.setup('owner', 'owner-test-password')
        self.client = TestClient(make_app(self.manager))
        self.client.cookies.set(SESSION_COOKIE, self.manager.create_session_trusted('owner'))

    def tearDown(self):
        self.client.close()

    def invite(self, name='teammate'):
        response = self.client.post('/api/auth/invitations', json={'username':name})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def accept(self, invitation, **extra):
        return self.client.post('/api/auth/accept-invitation', json={
            'token': invitation['token'], 'username':invitation['username'],
            'password':'member-test-password', **extra})

    def test_corrupt_account_file_cannot_reopen_owner_setup(self):
        broken = self.path.parent/'broken.json'
        broken.write_text('{broken')
        with self.assertRaises(RuntimeError):AuthManager(str(broken))

    def test_invitation_limits_and_long_unicode_password(self):
        self.assertEqual(self.client.post('/api/auth/invitations',json={'username':'a'*65}).status_code,422)
        invite=self.invite()
        self.assertEqual(self.accept(invite,password='é'*40).status_code,400)
        self.assertEqual(self.accept(invite).status_code,200)

    def test_preference_concurrent_owners_preserve_records(self):
        from routes import prefs_routes as prefs
        prefs.PREFS_FILE=str(self.path.parent/'race-prefs.json')
        with ThreadPoolExecutor(8) as pool:
            list(pool.map(lambda n:prefs._save_for_user('person'+str(n),{'theme':n}),range(20)))
        for n in range(20):self.assertEqual(prefs._load_for_user('person'+str(n)),{'theme':n})

    def test_member_cannot_revoke_invites_or_use_server_vault_cli(self):
        invite=self.invite()
        self.manager.create_user('member','member-password')
        self.client.cookies.set(SESSION_COOKIE,self.manager.create_session_trusted('member'))
        self.assertEqual(self.client.delete('/api/auth/invitations/'+invite['id']).status_code,403)
        self.assertEqual(self.client.get('/api/vault/config').status_code,403)
        self.assertEqual(self.client.put('/api/prefs/is_admin',json={'value':True}).status_code,200)
        self.assertFalse(self.manager.is_admin('member'))

    def test_first_setup_is_unique(self):
        self.assertFalse(self.manager.setup('second-owner', 'password-long'))
        with ThreadPoolExecutor(4) as pool:
            self.assertFalse(any(pool.map(lambda _: self.manager.setup('racer','long-password'), range(4))))
        self.assertEqual([u['username'] for u in self.manager.list_users()], ['owner'])

    def test_complete_invitation_persists_single_use_regular_user(self):
        invite = self.invite()
        self.assertNotIn(invite['token'], self.path.read_text())
        self.assertEqual(self.accept(invite, is_admin=True).status_code, 200)
        self.assertFalse(self.manager.is_admin('teammate'))
        self.assertTrue(self.manager.verify_password('teammate', 'member-test-password'))
        self.assertEqual(self.accept(invite).status_code, 400)
        restored = AuthManager(str(self.path))
        self.assertTrue(restored.verify_password('teammate', 'member-test-password'))
        self.assertEqual(restored.list_invitations(), [])

    def test_public_signup_and_toggle_denied_even_if_legacy_enabled(self):
        self.manager._config['signup_enabled'] = True
        self.assertFalse(self.client.get('/api/auth/status').json()['signup_enabled'])
        self.assertEqual(self.client.post('/api/auth/signup', json={'username':'intruder','password':'password-long'}).status_code,403)
        self.assertEqual(self.client.put('/api/auth/open-signup',json={'enabled':True}).status_code,409)
        self.assertEqual(self.client.post('/api/auth/signup-toggle').status_code,409)

    def test_invite_create_and_list_are_admin_only(self):
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/api/auth/invitations').status_code,403)
        self.assertEqual(self.client.post('/api/auth/invitations',json={'username':'intruder'}).status_code,403)
        self.manager.create_user('member','long-password')
        self.client.cookies.set(SESSION_COOKIE,self.manager.create_session_trusted('member'))
        self.assertEqual(self.client.get('/api/auth/invitations').status_code,403)
        self.assertEqual(self.client.get('/vault/admin',follow_redirects=False).status_code,403)

    def test_wrong_name_and_token_do_not_consume_invitation(self):
        invite=self.invite()
        self.assertEqual(self.accept(invite,username='other').status_code,400)
        self.assertEqual(self.accept(invite,token='wrong').status_code,400)
        self.assertEqual(self.accept(invite).status_code,200)

    def test_expired_and_revoked_invitation(self):
        invite=self.invite()
        self.manager._config['invitations'][invite['id']]['expires']=0
        self.assertEqual(self.accept(invite).status_code,400)
        fresh=self.invite('fresh')
        self.assertEqual(self.client.delete('/api/auth/invitations/'+fresh['id']).status_code,200)
        self.assertEqual(self.accept(fresh).status_code,400)

    def test_username_validation_and_duplicates(self):
        for name in ['../root', 'internal-tool', 'api', '', 'has spaces', 'owner']:
            self.assertEqual(self.client.post('/api/auth/invitations',json={'username':name}).status_code,409,name)
        self.invite()
        self.assertEqual(self.client.post('/api/auth/invitations',json={'username':'teammate'}).status_code,409)

    def test_single_use_under_race(self):
        invite=self.invite()
        with ThreadPoolExecutor(4) as pool:
            results=list(pool.map(lambda _:self.manager.accept_invitation(invite['token'],'teammate','long-password'),range(4)))
        self.assertEqual(sum(results),1)

    def test_failed_disk_write_cannot_consume_or_create(self):
        invite=self.invite()
        with patch('core.auth._atomic_write_json',side_effect=OSError('test failure')):
            with self.assertRaises(OSError):
                self.manager.accept_invitation(invite['token'],'teammate','long-password')
        self.assertNotIn('teammate',self.manager.users)
        self.assertEqual(self.accept(invite).status_code,200)

    def test_creator_demoted_invalidates_pending_invite(self):
        invite=self.invite()
        self.manager._config['users']['owner']['is_admin']=False
        self.assertEqual(self.accept(invite).status_code,400)

    def test_removed_name_cannot_inherit_retained_data(self):
        self.manager.create_user('former','password-long')
        self.assertTrue(self.manager.delete_user('former','owner'))
        self.assertFalse(self.manager.create_user('former','other-password'))
        with self.assertRaises(ValueError):self.manager.create_invitation('former','owner')

    def test_individual_preferences_and_modes_survive_restart(self):
        from routes import prefs_routes as prefs
        prefs.PREFS_FILE=str(self.path.parent/'prefs.json')
        self.manager.create_user('member','member-password')
        owner_cookie=self.client.cookies.get(SESSION_COOKIE)
        self.client.put('/api/prefs/theme',json={'value':{'name':'Temple'}})
        self.client.patch('/api/home/profile',json={'mode':'ai-free'})
        self.assertEqual(self.client.get('/api/auth/invitations').status_code,200)
        self.client.cookies.set(SESSION_COOKIE,self.manager.create_session_trusted('member'))
        self.assertIsNone(self.client.get('/api/prefs/theme').json()['value'])
        self.client.put('/api/prefs/theme',json={'value':{'name':'Light'}})
        self.client.patch('/api/home/profile',json={'mode':'full'})
        self.client.cookies.set(SESSION_COOKIE,owner_cookie)
        self.assertEqual(self.client.get('/api/prefs/theme').json()['value'],{'name':'Temple'})
        self.assertEqual(prefs._load_for_user('member')['theme'],{'name':'Light'})

    def test_anonymous_cannot_read_or_write_preferences(self):
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/api/prefs').status_code,401)
        self.assertEqual(self.client.put('/api/prefs/theme',json={'value':'bad'}).status_code,401)

    def test_vault_state_and_cli_environment_are_personal(self):
        vault_accounts.save_config('alpha',{'email':'alpha@example.invalid','session':'alpha-secret'})
        self.assertEqual(vault_accounts.load_config('beta'),{})
        with patch.dict(os.environ,{'BW_SESSION':'global-secret','BW_PASSWORD':'global-password'}):
            a=vault_accounts.cli_environment('alpha');b=vault_accounts.cli_environment('beta')
        self.assertNotEqual(a['BITWARDENCLI_APPDATA_DIR'],b['BITWARDENCLI_APPDATA_DIR'])
        self.assertNotIn('BW_SESSION',a);self.assertNotIn('BW_PASSWORD',a)
        self.assertEqual(vault_accounts.load_config('alpha')['session'],'alpha-secret')
        with self.assertRaises(ValueError):vault_accounts.load_config(None)

    def test_vault_routes_both_modes_never_expose_session(self):
        self.manager.create_user('vault-member','password-long',is_admin=True)
        self.client.cookies.set(SESSION_COOKIE,self.manager.create_session_trusted('vault-member'))
        vault_accounts.save_config('vault-member',{'email':'member@example.invalid','session':'keep-secret'})
        for mode in ['full','ai-free']:
            self.client.patch('/api/home/profile',json={'mode':mode})
            with patch('routes.vault.vault_routes._check_bw_installed',return_value=False):
                response=self.client.get('/api/vault/config')
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['email'],'member@example.invalid')
            self.assertNotIn('keep-secret',response.text)

    def test_vault_cli_receives_owner_directory_and_password_stdin(self):
        class Process:
            returncode=0
            async def communicate(self, input=None):
                self.input=input
                return b'ok',b''
        process=Process()
        with patch('routes.vault.vault_routes.asyncio.create_subprocess_exec',return_value=process) as launch:
            asyncio.run(_run_bw(['unlock','--raw'],input_text='test-password\n',owner='alpha'))
        args,kwargs=launch.call_args
        self.assertNotIn('test-password',' '.join(args))
        self.assertEqual(process.input,b'test-password\n')
        self.assertEqual(kwargs['env']['BITWARDENCLI_APPDATA_DIR'],str(vault_accounts.account_dir('alpha')/'cli'))


if __name__=='__main__':unittest.main(verbosity=2)
