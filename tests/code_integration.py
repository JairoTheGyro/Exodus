"""Isolated model-gateway tests. Never reads or changes the user's model database.
Run: docker exec -i sovereign-hub-odysseus-1 python - < tests/code_integration.py
"""
import os
import tempfile
import unittest
import json
from types import SimpleNamespace
from unittest.mock import patch

root = tempfile.TemporaryDirectory(prefix='exodus-code-tests-')
os.environ['ODYSSEUS_DATA_DIR'] = root.name
os.environ['DATABASE_URL'] = 'sqlite:///' + root.name + '/app.db'
os.environ['AUTH_ENABLED'] = 'true'
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.database import Base, ModelEndpoint, SessionLocal, engine
from routes.code_routes import setup_code_routes
from src.harness_bridge import connection, bridge_owner, model_id

Base.metadata.create_all(engine)
app = FastAPI()
app.state.auth_manager = SimpleNamespace(is_configured=True, is_admin=lambda user: user == 'admin')
@app.middleware('http')
async def identity(request, call_next):
    request.state.current_user = bridge_owner(request) or request.headers.get('x-test-user')
    return await call_next(request)
app.include_router(setup_code_routes())
with SessionLocal() as db:
    db.add_all([
        ModelEndpoint(id='local', owner='admin', name='Local fixture', base_url='http://localhost:9900/v1',
                      cached_models='["fixture", "hidden"]', hidden_models='["hidden"]', api_key='never-export-this'),
        ModelEndpoint(id='foreign', owner='other', name='Foreign', base_url='http://localhost:9901/v1', cached_models='["fixture"]'),
        ModelEndpoint(id='disabled', owner='admin', name='Disabled', base_url='http://localhost:9902/v1', cached_models='["fixture"]', is_enabled=False),
        ModelEndpoint(id='image', owner='admin', name='Image', base_url='http://localhost:9903/v1', cached_models='["image"]', model_type='image'),
        ModelEndpoint(id='no-tools', owner='admin', name='No tools', base_url='http://localhost:9904/v1', cached_models='["fixture"]', supports_tools=False),
    ])
    db.commit()

class CodeChecks(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        response = self.client.post('/api/code/connect', headers={'x-test-user': 'admin'})
        self.assertEqual(response.json(), {'connected': True})
        self.auth = {'Authorization': 'Bearer ' + connection()['token']}
        self.request = {'model': model_id('local', 'fixture'), 'stream': True,
            'messages': [{'role': 'user', 'content': 'A disposable test request'}]}

    def test_authorization_is_narrow(self):
        self.assertEqual(self.client.get('/api/code/bridge/v1/models').status_code, 401)
        self.assertEqual(self.client.get('/api/code/bridge/v1/models', headers={'Authorization': 'Bearer wrong'}).status_code, 401)
        self.assertEqual(self.client.get('/api/code/status', headers=self.auth).status_code, 403)
        self.assertEqual(self.client.post('/api/code/connect', headers=self.auth).status_code, 403)
        self.assertEqual(self.client.post('/api/code/connect', headers={'x-test-user': 'other'}).status_code, 403)

    def test_catalog_filters_and_redacts(self):
        r = self.client.get('/api/code/bridge/v1/models', headers=self.auth)
        self.assertEqual([m['id'] for m in r.json()['data']], [model_id('local', 'fixture')])
        for secret in ['never-export-this', 'http://localhost:9900', 'endpoint_id']:
            self.assertNotIn(secret, r.text)

    def test_live_add_disable_and_remove(self):
        with SessionLocal() as db:
            db.add(ModelEndpoint(id='new', owner=None, name='Shared fixture', base_url='http://localhost:9910/v1', pinned_models='["fixture"]'))
            db.commit()
        try:
            ids = [m['id'] for m in self.client.get('/api/code/bridge/v1/models', headers=self.auth).json()['data']]
            self.assertEqual(len(ids), 2)
            self.assertNotEqual(ids[0], ids[1])
            with SessionLocal() as db:
                db.get(ModelEndpoint, 'new').is_enabled = False; db.commit()
            data = dict(self.request, model=model_id('new', 'fixture'))
            self.assertEqual(self.client.post('/api/code/bridge/v1/chat/completions', json=data, headers=self.auth).status_code, 404)
        finally:
            with SessionLocal() as db:
                db.query(ModelEndpoint).filter_by(id='new').delete(); db.commit()

    def test_tool_call_stream_roundtrip(self):
        captured = []
        async def provider(url, model, messages, **kwargs):
            captured.append((url, model, messages, kwargs))
            yield 'data: {"delta":"Consider the tool", "thinking":true}\n\n'
            yield 'data: {"type":"tool_calls","calls":[{"id":"call_test","name":"read_file","arguments":"{\\"path\\":\\"README.md\\"}"}]}\n\n'
            yield 'data: {"type":"usage","data":{"input_tokens":9,"output_tokens":7}}\n\n'
            yield 'data: [DONE]\n\n'
        self.request['tools'] = [{'type':'function','function':{'name':'read_file','parameters':{'type':'object'}}}]
        self.request['messages'] += [{'role':'assistant','content':None,'tool_calls':[{'id':'old','type':'function','function':{'name':'read_file','arguments':'{}'}}]}, {'role':'tool','tool_call_id':'old','content':'fixture file'}]
        with patch('src.llm_core.stream_llm', provider), patch('src.endpoint_resolver.resolve_endpoint_by_id', return_value=('http://fixture/v1', 'fixture', {'Authorization':'Bearer private-provider-key'})):
            r = self.client.post('/api/code/bridge/v1/chat/completions', json=self.request, headers=self.auth)
        self.assertEqual(r.status_code, 200)
        frames = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith('data: {')]
        tool = next(f['choices'][0]['delta']['tool_calls'] for f in frames if f['choices'] and 'tool_calls' in f['choices'][0]['delta'])
        self.assertEqual(tool[0]['function']['name'], 'read_file')
        self.assertEqual(tool[0]['id'], 'call_test')
        self.assertTrue(any(f.get('usage', {}).get('total_tokens') == 16 for f in frames))
        self.assertEqual(captured[0][2][-1]['tool_call_id'], 'old')
        self.assertEqual(captured[0][3]['tools'], self.request['tools'])
        self.assertNotIn('private-provider-key', r.text)
        self.assertTrue(r.text.endswith('data: [DONE]\n\n'))

    def test_provider_errors_are_not_exposed(self):
        async def fail(*args, **kwargs):
            yield 'event: error\ndata: {"error":"private-provider-key prompt content"}\n\n'
        with patch('src.llm_core.stream_llm', fail), patch('src.endpoint_resolver.resolve_endpoint_by_id', return_value=('http://fixture', 'fixture', {})):
            r = self.client.post('/api/code/bridge/v1/chat/completions', json=self.request, headers=self.auth)
        self.assertIn('upstream_error', r.text)
        self.assertNotIn('private-provider-key', r.text)
        self.assertNotIn('[DONE]', r.text)

    def test_invalid_and_missing_model_requests_fail(self):
        for data, code in [(dict(self.request, model='invented'),404), (dict(self.request,stream=False),400),
                           (dict(self.request,messages=[]),400), (dict(self.request,temperature=99),400)]:
            self.assertEqual(self.client.post('/api/code/bridge/v1/chat/completions', json=data, headers=self.auth).status_code, code)

    def test_revoked_administrator_loses_gateway(self):
        with patch.object(app.state.auth_manager, 'is_admin', lambda user: False):
            self.assertEqual(self.client.get('/api/code/bridge/v1/models', headers=self.auth).status_code,401)

if __name__ == '__main__':
    unittest.main(verbosity=2)
