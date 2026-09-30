"""Run with: docker exec -i sovereign-hub-odysseus-1 python - < tests/searxng_integration.py"""
import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch

sandbox = tempfile.TemporaryDirectory()
os.environ['ODYSSEUS_DATA_DIR'] = sandbox.name
os.environ['DATABASE_URL'] = 'sqlite:///' + sandbox.name + '/test.db'
import httpx
from services.search import providers as p
from src.agent_tools import TOOL_HANDLERS
from src.tool_schemas import function_call_to_tool_block


def response(payload, status=200):
    return httpx.Response(status, json=payload, request=httpx.Request('GET', 'http://search/search'))

class SearchTests(unittest.TestCase):
    def setUp(self):
        self.settings = patch.object(p, '_get_search_settings', return_value={})
        self.settings.start()
        self.addCleanup(self.settings.stop)

    def test_request_and_bounded_clean_results(self):
        rows = [None, {'url': 'javascript:bad'}, {'url': 'http://[bad'}]
        rows += [{'url': f'https://example.org/{i}', 'title': '<b>Title</b>', 'content': '<p>' + 'x'*2000 + '</p>'} for i in range(9)]
        with patch.object(p.httpx, 'get', return_value=response({'results': rows})) as get:
            result = p.compact_searxng_search(' query ', categories='science')
        self.assertEqual(len(result), 5)
        self.assertEqual(result[0]['title'], 'Title')
        self.assertEqual(len(result[0]['content']), 1000)
        self.assertEqual(set(result[0]), {'title', 'url', 'content'})
        kwargs = get.call_args.kwargs
        self.assertEqual(kwargs['timeout'], 5.0)
        self.assertFalse(kwargs['follow_redirects'])
        self.assertEqual(kwargs['params']['format'], 'json')
        self.assertEqual(kwargs['params']['q'], 'query')
        self.assertEqual(kwargs['params']['categories'], 'science')
        get.assert_called_once()

    def test_count_duplicates_and_default_category(self):
        rows = [{'url':f'https://example.org/{i//2}'} for i in range(12)]
        with patch.dict(os.environ, {'SEARXNG_CATEGORIES':'general'}), patch.object(p.httpx, 'get', return_value=response({'results': rows})) as get:
            self.assertEqual(len(p.compact_searxng_search('q', 3)), 3)
            self.assertEqual(get.call_args.kwargs['params']['categories'], 'general')

    def test_errors_and_empty_results(self):
        for value in (response({},403), response({}), response([]), response({},500)):
            with self.subTest(status=value.status_code), patch.object(p.httpx, 'get', return_value=value):
                with self.assertRaises(p.SearXNGUnavailable): p.compact_searxng_search('q')
        for exc in (httpx.ConnectError('private detail'), httpx.ReadTimeout('private detail')):
            with patch.object(p.httpx, 'get', side_effect=exc):
                with self.assertRaises(p.SearXNGUnavailable) as raised: p.compact_searxng_search('q')
                self.assertNotIn('private detail', str(raised.exception))
        with patch.object(p.httpx, 'get', return_value=response({'results':[]})):
            self.assertEqual(p.compact_searxng_search('q'), [])
        with self.assertRaises(ValueError): p.compact_searxng_search(' ')

    def test_registered_agent_and_native_arguments(self):
        block = function_call_to_tool_block('web_search', json.dumps({'queries':'q','categories':'science','time_filter':'year'}))
        self.assertEqual(json.loads(block.content), {'query':'q','categories':'science','time_filter':'year'})
        with patch.object(p.httpx, 'get', return_value=response({'results':[{'title':'Source','url':'https://example.org','content':'Evidence'}]})), patch('src.search.comprehensive_web_search', side_effect=AssertionError('Should not fetch pages')):
            result = asyncio.run(TOOL_HANDLERS['web_search'](block.content, {}))
        self.assertEqual(result['exit_code'], 0)
        self.assertTrue(result['untrusted_content'])
        self.assertIn('<!-- SOURCES:', result['output'])
        self.assertEqual(json.loads(result['output'].split('\n\n')[0])['results'][0]['content'], 'Evidence')

    def test_agent_failure(self):
        with patch.object(p.httpx, 'get', side_effect=httpx.ConnectError('private')):
            result = asyncio.run(TOOL_HANDLERS['web_search']('q', {}))
        self.assertEqual(result['exit_code'], 1)
        self.assertIn('unavailable', result['error'])
        self.assertNotIn('private', result['error'])

if __name__ == '__main__': unittest.main()
