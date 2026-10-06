"""Offline compatibility checks: synthetic mail only, no provider or live data."""
import ast
import asyncio
import json
import logging
import shlex
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def load_function(path, name, namespace):
    """Execute the actual function without starting unrelated app services."""
    tree = ast.parse((ROOT / path).read_text())
    node = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    node.decorator_list = []
    node.args.defaults = [ast.Constant(None) for _ in node.args.defaults]
    node.args.kw_defaults = [ast.Constant(None) if n is not None else None for n in node.args.kw_defaults]
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), path, 'exec'), namespace)
    return namespace[name]


MAIL = {
    b'1': {'subject': 'Reminder (Odysseus): old', 'from': 'me@example.invalid'},
    b'2': {'subject': 'Reminder (Exodus): new', 'from': 'me@example.invalid'},
    b'3': {'subject': 'Different subject', 'from': 'other@example.invalid', 'x-odysseus-kind': 'reminder'},
    b'4': {'subject': 'Reminder: unrelated', 'from': 'other@example.invalid'},
    b'5': {'subject': 'Reminder: legacy own', 'from': 'me@example.invalid'},
    b'6': {'subject': 'Normal message', 'from': 'me@example.invalid'},
}


def matches(criteria, mail):
    """Small IMAP SEARCH evaluator for the protocol subset under test."""
    lexer = shlex.shlex(criteria, posix=True, punctuation_chars='()')
    lexer.whitespace_split = True
    tokens = []
    for token in lexer:
        tokens.extend(list(token) if token and set(token) <= {'(', ')'} else [token])
    def parse(i):
        token = tokens[i].upper()
        if token == '(':
            values = []; i += 1
            while tokens[i] != ')':
                value, i = parse(i); values.append(value)
            return all(values), i + 1
        if token == 'OR':
            left, i = parse(i + 1); right, i = parse(i)
            return left or right, i
        if token == 'HEADER':
            return tokens[i + 2].lower() in mail.get(tokens[i + 1].lower(), '').lower(), i + 3
        if token in ('SUBJECT', 'FROM'):
            return tokens[i + 1].lower() in mail[token.lower()].lower(), i + 2
        raise AssertionError(f'Unexpected IMAP search token {token}')
    result, end = parse(0)
    assert end == len(tokens)
    return result


@pytest.mark.parametrize('sender,expected', [(None, {b'1', b'2', b'3'}), ('me@example.invalid', {b'1', b'2'})])
def test_reminder_list_accepts_both_names_and_preserves_sender_scope(sender, expected):
    queries = []
    conn = Mock(); conn.select.return_value = ('OK', [])
    def search(connection, criteria):
        queries.append(criteria)
        return 'OK', [b'']  # Stop before fetching unrelated message bodies.
    release = Mock()
    namespace = {'_pooled_connect': Mock(return_value=(conn, False)), '_q': lambda s: s,
                 '_imap_uid_search': search, '_pooled_release': release,
                 'logger': logging.getLogger(__name__), 'EmailNotConfiguredError': type('NotConfigured', (Exception,), {})}
    function = load_function('routes/email_routes.py', '_list_emails_sync', namespace)
    result = function('INBOX', 50, 0, 'reminders', 'test-account', from_addr=sender, owner='alice')
    assert 'error' not in result
    assert {uid for uid, mail in MAIL.items() if matches(queries[0], mail)} == expected
    namespace['_pooled_connect'].assert_called_once_with('test-account', owner='alice')
    release.assert_called_once_with('test-account', conn, ok=True, owner='alice')


def test_reminder_cleanup_handles_old_new_and_marker_without_unrelated_mail():
    removed = []; conn = Mock()
    conn.select.side_effect = lambda folder: ('OK' if folder == 'INBOX' else 'NO', [])
    def uid(op, *args):
        if op == 'SEARCH':
            return 'OK', [b' '.join(uid for uid, mail in MAIL.items() if matches(args[-1], mail))]
        if op == 'STORE': removed.append(args[0])
        return 'OK', []
    conn.uid.side_effect = uid
    @contextmanager
    def imap(account_id, *, owner):
        assert account_id == 'test-account' and owner == 'alice'
        yield conn
    owner_check = Mock()
    function = load_function('routes/email_routes.py', 'delete_odysseus_reminder_emails', {
        '_imap': imap, '_assert_owns_account': owner_check,
        '_get_email_config': lambda *a, **k: {'from_address': 'me@example.invalid'},
        '_detect_sent_folder': lambda c: None, '_q': lambda s: s,
        '_invalidate_list_cache': Mock(), 'logger': logging.getLogger(__name__),
    })
    result = asyncio.run(function(account_id='test-account', permanent=False, owner='alice'))
    assert result['success'] and result['deleted'] == 4
    assert set(removed) == {b'1', b'2', b'3', b'5'}
    assert len(removed) == len(set(removed))
    owner_check.assert_called_once_with('test-account', 'alice')


@pytest.mark.parametrize('name,args', [
    ('_minimal_odysseus_doc_messages', ([], None, True)),
    ('_minimal_odysseus_doc_messages', ([], None, False)),
    ('_minimal_odysseus_notes_messages', ([],)),
    ('_minimal_odysseus_general_messages', ([], False)),
])
def test_specialized_model_identity_remains_compatible(name, args):
    function = load_function('src/agent_loop.py', name, {
        '_extract_last_user_message': lambda m: 'hello',
        '_minimal_saved_memory_message': lambda m: None,
        '_minimal_recent_notes_tool_context_message': lambda m: None,
    })
    messages = function(*args)
    assert messages[0]['content'].startswith('You are Odysseus.')
    assert messages[-1] == {'role': 'user', 'content': 'hello'}


def test_provider_request_identity():
    from src.copilot import copilot_headers
    from src.chatgpt_subscription import chatgpt_headers
    from src.endpoint_resolver import build_headers
    headers = copilot_headers(None)
    assert headers['User-Agent'] == 'Odysseus/1.0'
    assert headers['Editor-Version'] == 'Odysseus/1.0'
    assert chatgpt_headers(None)['User-Agent'] == 'Odysseus ChatGPT Subscription'
    assert build_headers(None, 'https://openrouter.ai/api/v1')['X-OpenRouter-Title'] == 'Odysseus'


def test_original_icon_paths_contain_real_correctly_sized_images():
    manifest = json.loads((ROOT / 'static/manifest.json').read_text())
    assert manifest['name'] == manifest['short_name'] == 'Exodus'
    for entry in manifest['icons']:
        path = ROOT / 'static' / entry['src']
        assert not path.is_symlink()
        with Image.open(path) as image:
            assert image.format == 'PNG'
            assert image.size == tuple(map(int, entry['sizes'].split('x')))
            image.verify()
    path = ROOT / 'static/icon.ico'
    assert not path.is_symlink()
    with Image.open(path) as image:
        assert image.format == 'ICO'
        assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= image.ico.sizes()
        for size in image.ico.sizes(): image.ico.getimage(size).load()


def test_upstream_setup_template_copies_and_preserves_existing_settings(tmp_path):
    import os
    template = (ROOT / '.env.example').read_bytes()
    (tmp_path / '.env.example').write_bytes(template)
    function = load_function('setup.py', 'create_env', {'os': os, 'BASE_DIR': str(tmp_path)})
    function()
    assert (tmp_path / '.env').read_bytes() == template
    (tmp_path / '.env').write_text('LOCAL_SETTING=keep-me\n')
    function()
    assert (tmp_path / '.env').read_text() == 'LOCAL_SETTING=keep-me\n'
    assert not (ROOT / 'env.example').exists()
