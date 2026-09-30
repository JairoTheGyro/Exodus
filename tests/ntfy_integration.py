"""Run inside Exodus: python - < tests/ntfy_integration.py. Uses no LLM or user data."""
import asyncio,json,os,tempfile,time,unittest,uuid
from unittest.mock import patch
from types import SimpleNamespace
_temp=tempfile.TemporaryDirectory(prefix='ntfy-tests-')
os.environ['ODYSSEUS_DATA_DIR']=_temp.name
os.environ['DATABASE_URL']='sqlite:///'+_temp.name+'/test.db'
import httpx
from src import notifications as n
from src.agent_tools import TOOL_HANDLERS
from src.tool_schemas import function_call_to_tool_block
from src.tool_execution import execute_tool_block, NO_TOOL_SECURITY_CONTEXT
from src.home_store import database,save

class FakeClient:
    calls=[]
    error=False
    def __init__(self,**kwargs): self.options=kwargs
    async def __aenter__(self): return self
    async def __aexit__(self,*args): pass
    async def post(self,url,**kwargs):
        self.calls.append((url,kwargs,self.options))
        if self.error: raise httpx.ConnectError('secret server details')
        return SimpleNamespace(is_success=True)

class Checks(unittest.TestCase):
    def setUp(self):
        FakeClient.calls=[];FakeClient.error=False
        self.env=patch.dict(os.environ,{'NTFY_ENABLED':'true','NTFY_DEFAULT_TOPIC':'exodus-alerts','NTFY_CACHE_MESSAGES':'false'})
        self.env.start();self.addCleanup(self.env.stop)

    def test_payload_and_timeout(self):
        with patch.object(n,'_validated_transport',return_value=None), patch.object(n.httpx,'AsyncClient',FakeClient):
            r=asyncio.run(n.dispatch_notification('body',title='Title\r\nInjected',priority=4,tags=['bell']))
        self.assertEqual(r['status'],'sent')
        url,kw,options=FakeClient.calls[0]
        self.assertTrue(url.endswith('/exodus-alerts'))
        self.assertEqual(kw['content'],b'body')
        self.assertNotIn('\n',kw['headers']['Title'])
        self.assertEqual(kw['headers']['Priority'],'4')
        self.assertEqual(kw['headers']['Tags'],'bell')
        self.assertEqual(kw['headers']['Firebase'],'no')
        self.assertEqual(kw['headers']['Cache'],'no')
        self.assertEqual(options['timeout'],3)
        self.assertFalse(options['follow_redirects'])

    def test_offline_and_invalid_inputs(self):
        with patch.object(n,'_validated_transport',return_value=None), patch.object(n.httpx,'AsyncClient',FakeClient):
            FakeClient.error=True
            r=asyncio.run(n.dispatch_notification('body'))
            self.assertEqual(r['status'],'failed');self.assertNotIn('secret',str(r))
            for kwargs in ({'topic':'../admin'},{'priority':9},{'tags':['a\nb']}):
                self.assertEqual(asyncio.run(n.dispatch_notification('body',**kwargs))['status'],'failed')

    def test_disabled_and_private_context(self):
        with patch.object(n,'_validated_transport') as transport:
            with patch.dict(os.environ,{'NTFY_ENABLED':'false'}):
                self.assertEqual(asyncio.run(n.dispatch_notification('body'))['status'],'skipped')
            self.assertEqual(asyncio.run(n.dispatch_notification('body',incognito=True))['status'],'skipped')
            with database() as db: save('private-user',{'mode':'ai-free'},db)
            self.assertNotEqual(asyncio.run(n.dispatch_notification('body',owner='private-user',ai=True))['status'],'sent')
            transport.assert_not_called()
        with patch('src.integrations.load_integrations',return_value=[{'preset':'ntfy','enabled':False,'base_url':'http://ntfy'}]):
            self.assertEqual(asyncio.run(n.dispatch_notification('body'))['status'],'skipped')

    def test_bounded_timeout(self):
        class Slow(FakeClient):
            async def post(self,*a,**kw): await asyncio.sleep(30)
        with patch.object(n,'_validated_transport',return_value=None),patch.object(n.httpx,'AsyncClient',Slow):
            start=time.monotonic();result=asyncio.run(n.dispatch_notification('body'))
        self.assertEqual(result['status'],'failed');self.assertLess(time.monotonic()-start,3.6)

    def test_queue_does_not_wait(self):
        import threading
        release=threading.Event()
        async def slow(*a,**kw):
            await asyncio.to_thread(release.wait,2)
            return {'status':'sent'}
        with patch.object(n,'dispatch_notification',slow):
            start=time.monotonic();self.assertTrue(n.enqueue_notification('body'))
            self.assertLess(time.monotonic()-start,0.2);release.set()

    def test_agent_dispatch_and_policies(self):
        block=function_call_to_tool_block('notify_user',json.dumps({'message':'Done'}))
        with patch('src.tool_security.owner_is_admin_or_single_user',return_value=True),patch('src.tool_execution._owner_is_admin',return_value=True),patch.object(n,'_validated_transport',return_value=None),patch.object(n.httpx,'AsyncClient',FakeClient):
            _,result=asyncio.run(execute_tool_block(block,owner='admin-test',security_context=NO_TOOL_SECURITY_CONTEXT))
            self.assertEqual(result['exit_code'],0,result)
            _,blocked=asyncio.run(execute_tool_block(block,owner='admin-test',disabled_tools={'notify_user'},security_context=NO_TOOL_SECURITY_CONTEXT))
            self.assertNotEqual(blocked['exit_code'],0)
        with patch('src.tool_security.owner_is_admin_or_single_user',return_value=False):
            r=asyncio.run(TOOL_HANDLERS['notify_user'](block.content,{'owner':'other'}))
            self.assertEqual(r['exit_code'],1)
        from src.tool_security import _PLAN_MODE_KNOWN_MUTATORS, NON_ADMIN_BLOCKED_TOOLS
        self.assertIn('notify_user',_PLAN_MODE_KNOWN_MUTATORS)
        self.assertIn('notify_user',NON_ADMIN_BLOCKED_TOOLS)

    def test_live_delivery(self):
        async def live():
            topic='exodus-test-'+uuid.uuid4().hex
            base=os.environ.get('NTFY_BASE_URL','http://ntfy:80').rstrip('/')
            async with httpx.AsyncClient(timeout=5) as client:
                async with client.stream('GET',base+'/'+topic+'/json') as response:
                    response.raise_for_status()
                    lines=response.aiter_lines()
                    await anext(lines) # subscription open
                    r=await n.dispatch_notification('Disposable Exodus notification test.',topic=topic,title='Exodus test')
                    self.assertEqual(r['status'],'sent')
                    received=json.loads(await asyncio.wait_for(anext(lines),3))
                    self.assertEqual(received['message'],'Disposable Exodus notification test.')
        asyncio.run(live())

if __name__=='__main__': unittest.main()
