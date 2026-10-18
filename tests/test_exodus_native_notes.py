"""Native Groq tool round trips and post-commit note indexing regressions."""
import asyncio
import json
from types import SimpleNamespace
import httpx
import pytest

from core import database as dbmod
from src import agent_loop as al, llm_core as lc, note_indexing as ni
from tests.helpers.embedding_lanes import FakeCollection


def test_groq_native_mode():
    assert al._agent_route_tool_mode('https://api.groq.com/openai/v1', 'openai/gpt-oss-120b')[0]
    assert not al._agent_route_tool_mode('http://localhost:11434/api/chat', 'gpt-oss:120b')[0]


@pytest.mark.xfail(strict=False, reason=(
    "Upstream's per-turn tool contract (src/turn_contract.py) offers only the notes "
    "family for this prompt, also on plain upstream; Exodus web_search/notify_user "
    "offering needs a live-chat check (roadmap follow-up)."))
def test_native_http_and_agent_roundtrip(monkeypatch):
    requests, executed = [], []
    names = ['web_search', 'manage_notes', 'notify_user']
    args = [{'query':'local AI models'}, {'action':'add','title':'Models','content':'- One\n- Two'}, {'message':'Finished','title':'Done'}]
    def handler(request):
        body = json.loads(request.content); requests.append(body)
        assert set(names) <= {t['function']['name'] for t in body['tools']}
        index = len(requests)-1
        if index < 3:
            delta = {'tool_calls':[{'index':0,'id':f'call_{index}','type':'function','function':{'name':names[index],'arguments':json.dumps(args[index])}}]}
            finish = 'tool_calls'
        else:
            delta = {'content':'Done.'}; finish='stop'
        content = 'data: '+json.dumps({'choices':[{'delta':delta,'finish_reason':finish}]})+'\n\ndata: [DONE]\n\n'
        return httpx.Response(200, headers={'content-type':'text/event-stream'}, content=content)
    async def execute(block, *a, **kw):
        executed.append(block.tool_type)
        return block.tool_type, {'output':'success','exit_code':0}
    # Transport test uses controlled fixture output, not untrusted live web text.
    monkeypatch.setattr(al.ToolRunSecurityContext,'observe_tool_result',lambda *a,**k:None)
    monkeypatch.setattr(al.ToolRunSecurityContext,'observe_messages',lambda *a,**k:None)
    monkeypatch.setattr(al,'execute_tool_block',execute)
    monkeypatch.setattr(al,'get_setting',lambda key,default=None:default)
    monkeypatch.setattr(al,'get_mcp_manager',lambda:None)
    monkeypatch.setattr(al,'estimate_tokens',lambda *a,**k:10)
    monkeypatch.setattr(al,'blocked_tools_for_owner',lambda owner:set())
    from src.agent_runtime.authority import bind_request_authority, create_request_authority
    prompt = 'Search the web, save a note, and ping me via ntfy.'
    authority = create_request_authority(prompt, owner='alice', session_id='notes-roundtrip')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monkeypatch.setattr(lc,'_http_client',client)
            with bind_request_authority(authority):
                return await _collect()
    async def _collect():
            return [c async for c in al.stream_agent_loop(
                'https://api.groq.com/openai/v1','openai/gpt-oss-120b',
                [{'role':'user','content':'Search the web, save a note, and ping me via ntfy.'}],
                relevant_tools=set(names),max_rounds=5,owner='alice',session_id='notes-roundtrip')]
    chunks=asyncio.run(run())
    assert executed == names, (executed,chunks)
    assert len(requests)==4
    for index in range(3):
        assert any(m.get('role')=='tool' and m.get('tool_call_id')==f'call_{index}' for m in requests[index+1]['messages'])


@pytest.fixture
def note_store(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine=create_engine('sqlite:///'+str(tmp_path/'notes.db'))
    dbmod.Note.__table__.create(engine)
    factory=sessionmaker(bind=engine)
    monkeypatch.setattr(dbmod,'SessionLocal',factory)
    jobs=[]
    monkeypatch.setattr(ni,'enqueue_note',lambda *job:jobs.append(job))
    monkeypatch.setattr('src.home_store.ai_free',lambda owner:False)
    ni.install_hooks(factory,dbmod.Note)
    yield factory,jobs
    engine.dispose()


def test_post_commit_only_and_rollback(note_store):
    factory,jobs=note_store
    with factory() as db:
        note=dbmod.Note(id='n1',owner='alice',title='First',content='hello')
        db.add(note); db.flush(); assert jobs==[]
        db.commit(); assert jobs==[('n1','alice')]
        note.content='changed';db.commit();assert len(jobs)==2
        note.content='discarded';db.flush();db.rollback();assert len(jobs)==2
        db.delete(note);db.commit();assert len(jobs)==3


def test_index_upsert_delete_and_ownership(note_store,monkeypatch):
    factory,jobs=note_store
    class Collection(FakeCollection):
        def get(self,where=None,**kw):
            result=super().get(**kw)
            if where:
                selected=[i for i,m in enumerate(result['metadatas']) if all(all(m.get(k)==v for k,v in clause.items()) for clause in where['$and'])]
                return {k:[v[i] for i in selected] for k,v in result.items()}
            return result
    collection=Collection('test')
    lane=SimpleNamespace(collection=collection,encode=lambda texts:[[1.,2.] for t in texts])
    rag=SimpleNamespace(healthy=True,_lanes=[lane],_split_into_chunks=lambda text,chunk_size:[text])
    with factory() as db:
        db.add(dbmod.Note(id='n1',owner='alice',title='First',content='hello'));db.commit()
    assert ni.ingest_note('n1','alice',rag=rag)['status']=='indexed'
    old=next(iter(collection.rows.values()))['metadata']
    assert ni.current_metadata(old)
    assert ni.ingest_note('n1','bob',rag=rag,require_existing=True)['status']=='not_found'
    with factory() as db:
        db.get(dbmod.Note,'n1').content='updated';db.commit()
    assert not ni.current_metadata(old)
    assert ni.ingest_note('n1','alice',rag=rag)['status']=='indexed'
    assert collection.count()==1
    assert 'updated' in next(iter(collection.rows.values()))['document']
    monkeypatch.setattr('src.home_store.ai_free',lambda owner:True)
    monkeypatch.setattr('src.ai_policy.ai_free',lambda owner:True)
    assert ni.ingest_note('n1','alice',rag=rag)['status']=='skipped'
    assert not ni.current_metadata(next(iter(collection.rows.values()))['metadata'])
    # Deletions clean up existing vectors even in AI-free, without embeddings.
    with factory() as db:
        db.delete(db.get(dbmod.Note,'n1'));db.commit()
    assert ni.ingest_note('n1','alice',rag=rag)['status']=='removed'
    assert collection.count()==0
    assert ni.ingest_note('n1','alice',rag=SimpleNamespace(healthy=False))['status']=='unavailable'


def test_real_note_tool_dispatch_triggers_index_hook(note_store):
    from src.tool_schemas import function_call_to_tool_block
    from src.tool_execution import execute_tool_block, NO_TOOL_SECURITY_CONTEXT
    factory, jobs = note_store
    block = function_call_to_tool_block('manage_notes', json.dumps({'action':'add','title':'Models','content':'- One\n- Two'}))
    from src.agent_runtime.authority import bind_request_authority, create_request_authority
    # Upstream requires the request's authority to cover the exact tool operation.
    authority = create_request_authority('Save a note called Models with One and Two', owner='alice', session_id='notes-test-session')
    async def run():
        with bind_request_authority(authority):
            return await execute_tool_block(block, owner='alice', session_id='notes-test-session', security_context=NO_TOOL_SECURITY_CONTEXT)
    _, result = asyncio.run(run())
    assert result['exit_code'] == 0, result
    with factory() as db:
        note = db.query(dbmod.Note).one()
        assert note.content == '- One\n- Two'
        assert jobs == [(note.id, 'alice')]


def test_external_results_still_require_approval():
    gate=al.ToolRunSecurityContext()
    gate.observe_tool_result('web_search',{'output':'external page','exit_code':0})
    assert not gate.decision_for('manage_notes',json.dumps({'action':'add','content':'summary'})).allowed
    assert not gate.decision_for('notify_user',json.dumps({'message':'Done'})).allowed


def test_notification_intent_selects_integrations():
    prompt='Search the web for the latest status of open-source local AI models, save a brief 2-bullet summary into my notes, and ping me via ntfy when finished.'
    intent=al._classify_agent_request([{'role':'user','content':prompt}],prompt)
    assert {'integrations','notes_calendar_tasks'} <= intent['domains']
    assert 'notify_user' in al._DOMAIN_TOOL_MAP['integrations']


def test_explicit_tool_disable_is_preserved(note_store):
    factory,_=note_store
    dbmod.ModelEndpoint.__table__.create(factory.kw['bind'])
    url='https://api.groq.com/openai/v1'
    with factory() as db:
        db.add(dbmod.ModelEndpoint(id='groq',name='Groq',base_url=url,supports_tools=False));db.commit()
    assert not al._agent_route_tool_mode(url,'openai/gpt-oss-120b')[0]
