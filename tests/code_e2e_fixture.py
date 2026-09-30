"""Disposable local provider + real Exodus gateway for Harness transport testing.
Listens only in the Docker network during the test. No production DB or model.
"""
import os, tempfile, json
from types import SimpleNamespace
from pathlib import Path
root = tempfile.TemporaryDirectory(prefix='exodus-code-e2e-')
os.environ['ODYSSEUS_DATA_DIR'] = root.name
os.environ['DATABASE_URL'] = 'sqlite:///' + root.name + '/test.db'
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from core.database import Base, ModelEndpoint, SessionLocal, engine
from src.harness_bridge import BRIDGE_DIR, BRIDGE_FILE, model_id
from routes.code_routes import setup_code_routes
Base.metadata.create_all(engine)
BRIDGE_DIR.mkdir()
BRIDGE_FILE.write_text(json.dumps({'owner':'fixture-admin','token':'exodus_code_disposable_fixture_only'}))
with SessionLocal() as db:
    db.add(ModelEndpoint(id='fixture', owner='fixture-admin', name='EXPLICIT TEST FIXTURE',
        base_url='http://127.0.0.1:7094/fixture/v1', cached_models='["fixture"]', supports_tools=True))
    db.commit()
app = FastAPI()
app.state.auth_manager = SimpleNamespace(is_admin=lambda u: u=='fixture-admin')
app.include_router(setup_code_routes())
report = {'requests':0,'tool_result_received':False, 'tools':[]}
@app.get('/test/report')
def result(): return report
@app.get('/fixture/v1/models')
def fixture_models(): return {'data':[{'id':'fixture'}]}
@app.post('/fixture/v1/chat/completions')
async def complete(request:Request):
    b=await request.json(); report['requests']+=1
    report['tools']=[t['function']['name'] for t in b.get('tools',[])]
    is_second=any(m.get('role')=='tool' for m in b['messages'])
    async def chunks():
        def emit(delta,finish=None):return 'data: '+json.dumps({'id':'fixture-completion','object':'chat.completion.chunk','model':'fixture','choices':[{'index':0,'delta':delta,'finish_reason':finish}]})+'\n\n'
        if 'submit_workshop_app' in report['tools']:
            results = [m.get('content', '') for m in b['messages'] if m.get('role') == 'tool']
            report['tool_results'] = results
            report['tool_result_received'] = bool(results)
            if len(results) >= 2:
                yield emit({'content': 'Explicit test fixture: app submitted after repair.'}, 'stop')
            else:
                source = '<!doctype html><html><head><title>Explicit test fixture</title></head><body><button id="count">Count</button><script>let count = 0; document.getElementById("count").onclick = e => e.target.textContent = String(++count);</script></body></html>' if results else '<html><script>const broken = ;</script></html>'
                yield emit({'tool_calls': [{'index': 0, 'id': 'call_workshop_' + str(len(results)), 'type': 'function', 'function': {'name': 'submit_workshop_app', 'arguments': json.dumps({'source': source})}}]}, 'tool_calls')
        elif is_second:
            report['tool_result_received']=True
            report['tool_results']=[m.get('content') for m in b['messages'] if m.get('role')=='tool']
            yield emit({'content':'EXPLICIT TEST FIXTURE: model and tool-result round trip succeeded.'}, 'stop')
        else:
            # Only request a read-only shell operation, in the disposable folder.
            name=next((n for n in report['tools'] if n in ('bash','Bash','exec_command')),None)
            if not name:
                yield emit({'content':'EXPLICIT TEST FIXTURE: no bash tool exposed.'},'stop')
            else:
                yield emit({'tool_calls':[{'index':0,'id':'call_fixture','type':'function','function':{'name':name,'arguments':json.dumps({'command':'pwd','description':'Read the disposable test working directory','cmd':'pwd'})}}]},'tool_calls')
        yield 'data: [DONE]\n\n'
    return StreamingResponse(chunks(),media_type='text/event-stream')
if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='0.0.0.0',port=7094,log_level='warning')
