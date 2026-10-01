"""Exercise the actual template scanner and duplicate store with no AI provider."""
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from unittest.mock import Mock

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize('ai_free', [True, False])
@pytest.mark.parametrize('enabled', [True, False])
async def test_templates_independent_of_mode_and_missing_model(tmp_path, monkeypatch, ai_free, enabled):
    from routes import email_helpers as h, email_pollers as p
    from src import home_store

    db = tmp_path / 'mail.db'
    monkeypatch.setattr(h, 'SCHEDULED_DB', db)
    monkeypatch.setattr(p, 'SCHEDULED_DB', db)
    h._init_scheduled_db()
    settings = {
        'email_auto_reply': enabled,
        'email_auto_reply_message': 'I will reply tomorrow.',
        'email_auto_reply_enabled_at': (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        # These must not leak into the template-only scanner, even if enabled.
        'email_auto_summarize': True, 'email_auto_tag': True,
        'email_auto_spam': True, 'email_auto_calendar': True,
    }
    monkeypatch.setattr(p, '_load_settings', lambda: settings)
    monkeypatch.setattr(p, '_owner_for_email_account', lambda account: 'alice')
    monkeypatch.setattr(home_store, 'ai_free', lambda owner: ai_free)
    resolve = Mock(return_value=[])
    monkeypatch.setattr(p, 'resolve_task_candidates', resolve)
    def forbidden(*args, **kwargs):
        pytest.fail('Template reply invoked an AI operation')
    monkeypatch.setattr(p, 'task_llm_call_async', forbidden)
    monkeypatch.setattr(p, '_generate_scheduled_email_summary', forbidden)
    monkeypatch.setattr(p, '_detect_spam_folder', lambda conn: None)
    monkeypatch.setattr(p, '_get_email_config', lambda account, owner='': {'from_address': 'alice@example.test'})
    smtp = Mock()
    monkeypatch.setattr(p, '_send_smtp_message', smtp)

    msg = EmailMessage()
    msg['From'] = 'Bob <bob@example.test>'
    msg['To'] = 'alice@example.test'
    msg['Subject'] = 'Hello'
    msg['Message-ID'] = '<template-test@example.test>'
    msg['Date'] = format_datetime(datetime.now(timezone.utc))
    msg.set_content('Please get back to me.')
    class Mailbox:
        def select(self, *args, **kwargs):
            return 'OK', []
        def uid(self, action, *args):
            if action == 'SEARCH':
                return 'OK', [b'1']
            if action == 'FETCH':
                return 'OK', [(b'1', msg.as_bytes())]
            raise AssertionError(action)
        def logout(self):
            pass
    monkeypatch.setattr(p, '_imap_connect', lambda *args, **kwargs: Mailbox())

    result = await p._auto_summarize_pass_single(account_id='acct')
    assert 'Error:' not in result
    assert smtp.call_count == int(enabled)
    if enabled:
        assert smtp.call_args.args[2] == ['bob@example.test']
        assert 'sent 1 away reply' in result
        import email
        sent = email.message_from_string(smtp.call_args.args[3])
        assert sent.get_payload(0).get_payload(decode=True).decode() == settings['email_auto_reply_message']
        assert sent['Auto-Submitted'] == 'auto-replied'
    if ai_free:
        resolve.assert_not_called()
    else:
        assert 'No model configured' in result
    # A later scan must retain the existing duplicate-reply protection.
    await p._auto_summarize_pass_single(account_id='acct')
    assert smtp.call_count == int(enabled)


@pytest.mark.asyncio
async def test_ai_only_pass_never_runs_in_ai_free(monkeypatch):
    from routes import email_pollers as p
    from src import home_store
    monkeypatch.setattr(home_store, 'ai_free', lambda owner: True)
    monkeypatch.setattr(p, '_owner_for_email_account', lambda account: 'alice')
    connect = Mock()
    monkeypatch.setattr(p, '_imap_connect', connect)
    assert 'AI-free' in await p._scan_email_account(account_id='acct', away_only=False)
    connect.assert_not_called()
