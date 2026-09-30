"""Temporary browser QA server; uses only disposable data from the test harness.

Run in the installed Docker image with this checkout mounted read-only at /workspace:
python tests/workshop_browser_fixture.py
The server binds port 7071. Publish it to loopback only and remove after QA.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workshop_integration import app, SessionLocal, Document, MARKER
from fastapi.responses import HTMLResponse, FileResponse
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
# Replace the test harness's header-only wrapper with the actual trusted wrapper.
app.router.routes[:] = [r for r in app.router.routes if getattr(r, 'path', '') != '/static/workshop-frame.html']

@app.get('/static/workshop-frame.html')
def wrapper(): return FileResponse(ROOT / 'static/workshop-frame.html')

@app.get('/static/js/workshopRuntime.js')
def runtime(): return FileResponse(ROOT / 'static/js/workshopRuntime.js', media_type='application/javascript')

SOURCE = '''<!doctype html><html><head><title>Explicit QA fixture</title></head><body>
<h2>Test counter — not AI generated</h2><p id="count">Loading</p><button id="add">Add one and save</button>
<button id="network">Test blocked web request</button><button id="dom">Test account DOM isolation</button>
<button id="navigate">Test blocked frame navigation</button><p id="result"></p>
<script type="module">
await workshop.ready; let state=workshop.getState(); const count=document.getElementById('count');
const result=document.getElementById('result'); count.textContent='Saved count: '+(state.count||0);
document.getElementById('add').onclick=async()=>{try{state=await workshop.saveState({count:(state.count||0)+1});count.textContent='Saved count: '+state.count;}catch(e){result.textContent=e.message;}};
document.getElementById('network').onclick=async()=>{try{await fetch('http://127.0.0.1:7071/probe');result.textContent='FAIL: request allowed';}catch(e){result.textContent='PASS: web request blocked';}};
document.getElementById('dom').onclick=()=>{try{result.textContent=top.document.body.textContent;}catch(e){result.textContent='PASS: account DOM blocked';}};
document.getElementById('navigate').onclick=()=>{location.href='http://127.0.0.1:7071/probe';};
</script></body></html>'''
with SessionLocal() as db:
    db.query(Document).filter(Document.id == 'own').update({'current_content': MARKER + SOURCE})
    db.commit()

probes = []
@app.get('/probe')
def probe(): probes.append('request'); return HTMLResponse('FAIL: navigation escaped')

@app.get('/fixture-source')
def fixture_source(): return {'source': MARKER + SOURCE}

@app.get('/fixture-status')
def fixture_status(): return {'unexpected_network_requests': len(probes)}

@app.middleware('http')
async def fixture_user(request, call_next):
    # Only this disposable test server installs a test identity.
    headers = list(request.scope['headers'])
    headers.append((b'x-test-user', b'admin'))
    request.scope['headers'] = headers
    return await call_next(request)

PAGE = '''<!doctype html><html><head><title>Workshop isolated runtime QA</title></head><body>
<h1>Isolated Workshop QA — disposable test data</h1><p>No model or user data is used.</p>
<button id="open">Open test app</button><button id="reopen">Reopen test app</button><button id="check">Check stored entries</button>
<p id="stored"></p><iframe id="preview" title="Workshop test preview" style="width:1000px;height:400px"></iframe>
<script type="module" src="/fixture.js"></script></body></html>'''

@app.get('/')
def index(): return HTMLResponse(PAGE)

@app.get('/fixture.js')
def script():
    return HTMLResponse('''import {mountWorkshopPreview,workshopRequest} from '/static/js/workshopRuntime.js';
let cleanup;
async function open(){cleanup?.();const source=(await workshopRequest('/fixture-source')).source;cleanup=mountWorkshopPreview(document.getElementById('preview'),'own',source);}
document.getElementById('open').onclick=open;document.getElementById('reopen').onclick=open;
document.getElementById('check').onclick=async()=>{document.getElementById('stored').textContent=JSON.stringify({state:await workshopRequest('/api/workshop/own/state'),network:await workshopRequest('/fixture-status')});};
''', media_type='application/javascript')

if __name__ == '__main__': uvicorn.run(app, host='0.0.0.0', port=7071, log_level='warning')
