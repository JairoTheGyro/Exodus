"""Isolated integration checks. Run directly; never opens the user's data directory.

docker exec -i sovereign-hub-odysseus-1 python - < tests/workshop_integration.py
"""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

_temp = tempfile.TemporaryDirectory(prefix="sovereign-workshop-tests-")
os.environ["ODYSSEUS_DATA_DIR"] = _temp.name
os.environ["DATABASE_URL"] = "sqlite:///" + _temp.name + "/test.db"
os.environ["AUTH_ENABLED"] = "true"
os.environ["LOCALHOST_BYPASS"] = "false"

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import HTMLResponse
from core.database import Base, Document, ModelEndpoint, engine, SessionLocal
from core.middleware import SecurityHeadersMiddleware
from routes.workshop_routes import setup_workshop_routes, _state_path
from routes.document.document_routes import setup_document_routes
from src.workshop import MARKER, WorkshopBrief, assess_brief, normalize_workshop_source

Base.metadata.create_all(engine)
app = FastAPI()
app.state.auth_manager = SimpleNamespace(
    is_configured=True, is_admin=lambda user: user == "admin",
    get_privileges=lambda user: {"can_use_documents": user != "blocked"},
)

@app.middleware("http")
async def identity(request, call_next):
    request.state.current_user = request.headers.get("x-test-user")
    request.state.api_token = request.headers.get("x-test-token") == "yes"
    return await call_next(request)

app.add_middleware(SecurityHeadersMiddleware)
app.include_router(setup_workshop_routes())
app.include_router(setup_document_routes(None))

@app.get("/static/workshop-frame.html")
def frame():
    return HTMLResponse("wrapper")

BRIEF = dict(title="Packing list", description="A small checklist for packing things.", features="Add items and tick them off.")
SOURCE = '<!doctype html><html><head><title>Test fixture</title></head><body>Explicit test fixture</body></html>'
with SessionLocal() as db:
    db.add_all([
        Document(id="own", owner="admin", title="Fixture", language="html", current_content=MARKER + SOURCE),
        Document(id="other", owner="other", title="Fixture", language="html", current_content=MARKER + SOURCE),
        Document(id="plain", owner="admin", title="Plain HTML", language="html", current_content=SOURCE),
        ModelEndpoint(id="local-test", owner="admin", name="Test model", base_url="http://127.0.0.1:9999/v1", cached_models='["test-model"]', pinned_models='["test-model"]'),
        ModelEndpoint(id="foreign", owner="other", name="Other model", base_url="http://127.0.0.1:9998/v1", cached_models='["other-model"]'),
    ])
    db.commit()


class WorkshopChecks(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.headers["x-test-user"] = "admin"

    def test_risk_zones_and_normalization(self):
        self.assertEqual(assess_brief(WorkshopBrief(**BRIEF))["zone"], "green")
        self.assertEqual(assess_brief(WorkshopBrief(**BRIEF, audience="family"))["zone"], "yellow")
        for flags in [{"sensitive": True}, {"critical": True}, {"description": "Store medical records for patients"}]:
            self.assertEqual(assess_brief(WorkshopBrief(**(BRIEF | flags)))["zone"], "red")
        self.assertTrue(normalize_workshop_source('```html\n' + SOURCE + '\n```').startswith(MARKER))
        with self.assertRaises(ValueError): normalize_workshop_source('<html>unfinished')

    def test_existing_library_save_reopen_and_idempotent_retry(self):
        payload = {"title": "Workshop QA", "content": MARKER + SOURCE, "language": "html", "request_id": "831b5c6c-595a-4cc1-b85b-f5a351468048"}
        first = self.client.post('/api/document', json=payload)
        self.assertEqual(first.status_code, 200, first.text)
        again = self.client.post('/api/document', json=payload)
        self.assertEqual(first.json()['id'], again.json()['id'])
        doc_id = first.json()['id']
        loaded = self.client.get('/api/document/' + doc_id)
        self.assertEqual(loaded.json()['current_content'], payload['content'])
        library = self.client.get('/api/documents/library', params={"search": "Workshop QA"})
        self.assertEqual(library.status_code, 200, library.text)
        self.assertEqual(len(library.json()['documents']), 1)
        self.assertEqual(self.client.get('/api/workshop/' + doc_id + '/state').json(), {'revision': 0, 'data': {}})
        self.assertEqual(self.client.post('/api/document', json=payload | {'content': MARKER + SOURCE + 'changed'}).status_code, 409)

    def test_access_controls(self):
        for user, code in [(None, 401), ("blocked", 403)]:
            with TestClient(app) as client:
                headers = {"x-test-user": user} if user else {}
                self.assertEqual(client.post('/api/workshop/assess', json=BRIEF, headers=headers).status_code, code)
        self.assertEqual(self.client.get('/api/workshop/own/state', headers={"x-test-token": "yes"}).status_code, 403)
        self.assertEqual(self.client.get('/api/workshop/other/state').status_code, 404)
        self.assertEqual(self.client.get('/api/workshop/plain/state').status_code, 400)
        self.assertEqual(self.client.post('/api/workshop/generate', headers={"x-test-user": "other"}, json=BRIEF | {"endpoint_id": "local-test", "model": "test-model"}).status_code, 403)

    def test_state_roundtrip_conflict_size_and_corruption(self):
        path = '/api/workshop/own/state'
        initial = self.client.get(path).json()
        saved = self.client.put(path, json={"revision": initial['revision'], "data": {"items": ["hat"], "nested": {"checked": True}}})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.client.get(path).json(), saved.json())
        self.assertEqual(self.client.put(path, json={"revision": initial['revision'], "data": {}}).status_code, 409)
        self.assertEqual(self.client.put(path, json={"revision": saved.json()['revision'], "data": {"x": "x" * 100001}}).status_code, 413)
        self.assertEqual(self.client.put(path, json={"revision": saved.json()['revision'], "data": []}).status_code, 422)
        self.assertEqual(self.client.put('/api/workshop/other/state', json={"revision": 0, "data": {}}).status_code, 404)
        _state_path('own').write_text('{broken', encoding='utf-8')
        self.assertEqual(self.client.get(path).status_code, 409)
        self.assertEqual(self.client.put(path, json={"revision": 0, "data": {}}).status_code, 409)
        self.assertEqual(_state_path('own').read_text(), '{broken')
        _state_path('own').unlink()

    def test_model_options_owner_and_unavailable(self):
        result = self.client.get('/api/workshop/models')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual([m['endpoint_id'] for m in result.json()['models']], ['local-test'])
        self.assertNotIn('api_key', result.text)
        self.assertNotIn('base_url', result.text)
        response = self.client.post('/api/workshop/generate', json=BRIEF | {"endpoint_id": "missing", "model": "missing"})
        self.assertEqual(response.status_code, 400)

    def test_generation_uses_existing_provider_and_excludes_entries(self):
        with patch('src.endpoint_resolver.resolve_endpoint_by_id', return_value=('http://127.0.0.1:9999/v1', 'test-model', {})), patch('src.llm_core.llm_call_async', new_callable=AsyncMock) as model:
            model.return_value = SOURCE
            payload = BRIEF | {"engine": "direct", "endpoint_id": "local-test", "model": "test-model", "document_id": "own"}
            response = self.client.post('/api/workshop/generate', json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()['content'].startswith(MARKER))
            self.assertEqual(model.await_count, 1)
            self.assertIn('Existing app source', model.call_args.args[2][1]['content'])
            for changes, code in [({"sensitive": True}, 422), ({"audience": "public"}, 409), ({"document_id": "other"}, 404)]:
                self.assertEqual(self.client.post('/api/workshop/generate', json=payload | changes).status_code, code)
            self.assertEqual(model.await_count, 1)
            model.return_value = '<html>truncated'
            self.assertEqual(self.client.post('/api/workshop/generate', json=payload).status_code, 422)
            model.side_effect = ValueError('SECRET provider internals')
            failure = self.client.post('/api/workshop/generate', json=payload)
            self.assertEqual(failure.status_code, 502)
            self.assertNotIn('SECRET', failure.text)

    def test_harness_is_default_and_receives_only_brief_and_source(self):
        import httpx
        from src.harness_bridge import model_id
        payload = BRIEF | {"endpoint_id": "local-test", "model": "test-model", "document_id": "own"}
        with patch('routes.workshop_routes.httpx.AsyncClient') as factory:
            client = AsyncMock()
            factory.return_value.__aenter__.return_value = client
            client.post.return_value = httpx.Response(200, json={'source': SOURCE})
            response = self.client.post('/api/workshop/generate', json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['engine'], 'harness')
            sent = client.post.call_args.kwargs['json']
            self.assertEqual(sent['model'], model_id('local-test', 'test-model'))
            self.assertIn('Existing app source', sent['prompt'])
            self.assertIn('submit_workshop_app', sent['instructions'])
            self.assertNotIn('api_key', str(sent))
            self.assertNotIn('base_url', str(sent))
            self.assertEqual(set(sent), {'model', 'instructions', 'prompt'})
            client.post.return_value = httpx.Response(200, json={'source': '<html>truncated'})
            self.assertEqual(self.client.post('/api/workshop/generate', json=payload).status_code, 422)
            client.post.return_value = httpx.Response(500, text='SECRET internals')
            failure = self.client.post('/api/workshop/generate', json=payload)
            self.assertEqual(failure.status_code, 502)
            self.assertNotIn('SECRET', failure.text)
            client.post.side_effect = httpx.ConnectError('SECRET')
            self.assertEqual(self.client.post('/api/workshop/generate', json=payload).status_code, 503)
            client.post.side_effect = httpx.ReadTimeout('SECRET')
            self.assertEqual(self.client.post('/api/workshop/generate', json=payload).status_code, 504)

    def test_harness_rejects_non_tool_model_and_preserves_basic_builder(self):
        with SessionLocal() as db:
            endpoint = db.get(ModelEndpoint, 'local-test')
            endpoint.supports_tools = False
            db.commit()
        try:
            options = self.client.get('/api/workshop/models').json()['models']
            self.assertFalse(options[0]['harness_compatible'])
            response = self.client.post('/api/workshop/generate', json=BRIEF | {'endpoint_id': 'local-test', 'model': 'test-model'})
            self.assertEqual(response.status_code, 400)
            self.assertIn('supports coding tools', response.text)
            with patch('src.llm_core.llm_call_async', new_callable=AsyncMock, return_value=SOURCE):
                response = self.client.post('/api/workshop/generate', json=BRIEF | {'endpoint_id': 'local-test', 'model': 'test-model', 'engine': 'direct'})
                self.assertEqual(response.status_code, 200, response.text)
        finally:
            with SessionLocal() as db:
                db.get(ModelEndpoint, 'local-test').supports_tools = True
                db.commit()

    def test_wrapper_headers_do_not_relax_other_routes(self):
        response = self.client.get('/static/workshop-frame.html')
        policy = response.headers['content-security-policy']
        self.assertIn("frame-src 'none'", policy)
        self.assertIn("connect-src 'none'", policy)
        self.assertIn('sandbox allow-scripts;', policy)
        self.assertNotIn('allow-same-origin', policy)
        self.assertEqual(self.client.get('/other').headers['x-frame-options'], 'DENY')


if __name__ == '__main__':
    try: unittest.main()
    finally: engine.dispose(); _temp.cleanup()
