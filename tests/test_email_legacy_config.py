"""Mail config never inherits plaintext credentials or a different mailbox."""
from unittest.mock import Mock
import json

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def accounts(monkeypatch, tmp_path):
    from core import database
    from routes import email_helpers as helpers
    from src import secret_storage
    engine = create_engine("sqlite:///:memory:")
    database.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", factory)
    monkeypatch.setattr(secret_storage, "_KEY_PATH", tmp_path / ".app_key")
    monkeypatch.setattr(secret_storage, "_fernet", Fernet(Fernet.generate_key()))
    # Other tests reload src.secret_storage; make email_helpers decrypt with
    # the same module instance (and key) that encrypts the fixtures below.
    monkeypatch.setattr(helpers, "_decrypt", secret_storage.decrypt)
    monkeypatch.delenv("EXODUS_ALLOW_LEGACY_EMAIL_CONFIG", raising=False)
    monkeypatch.delenv("EXODUS_LEGACY_EMAIL_OWNER", raising=False)
    legacy = Mock(return_value={
        "smtp_host": "smtp.example.invalid", "smtp_user": "legacy@example.invalid",
        "smtp_password": "synthetic-legacy-password",
        "imap_host": "imap.example.invalid", "imap_user": "legacy@example.invalid",
        "imap_password": "synthetic-legacy-password", "imap_starttls": "false",
    })
    monkeypatch.setattr(helpers, "_load_settings", legacy)

    def add(account_id, owner="alice", enabled=True, default=False):
        with factory() as db:
            db.add(database.EmailAccount(
                id=account_id, owner=owner, enabled=enabled, is_default=default,
                name="Synthetic", imap_host="imap.example.invalid", imap_port=993,
                imap_user=f"{owner}@example.invalid", smtp_host="smtp.example.invalid",
                smtp_port=465, smtp_user=f"{owner}@example.invalid",
                smtp_password=secret_storage.encrypt("synthetic-database-password"),
                imap_password=secret_storage.encrypt("synthetic-database-password"),
            ))
            db.commit()
    yield helpers, factory, add, legacy
    engine.dispose()


def test_plaintext_settings_and_env_are_disabled_by_default(accounts, monkeypatch):
    h, _, _, legacy = accounts
    monkeypatch.setenv("IMAP_PASSWORD", "synthetic-environment-password")
    monkeypatch.setenv("EXODUS_LEGACY_EMAIL_OWNER", "alice")
    with pytest.raises(h.EmailNotConfiguredError):
        h._get_email_config(owner="alice")
    legacy.assert_not_called()


@pytest.mark.parametrize("owner,binding", [("alice", ""), ("bob", "alice"), ("", "alice")])
def test_explicit_opt_in_also_requires_exact_named_owner(accounts, monkeypatch, owner, binding):
    h, _, _, legacy = accounts
    monkeypatch.setenv("EXODUS_ALLOW_LEGACY_EMAIL_CONFIG", "true")
    monkeypatch.setenv("EXODUS_LEGACY_EMAIL_OWNER", binding)
    with pytest.raises(h.EmailNotConfiguredError):
        h._get_email_config(owner=owner)
    legacy.assert_not_called()


def test_opted_in_owner_can_use_legacy_config_without_changing_it(accounts, monkeypatch):
    h, _, _, legacy = accounts
    monkeypatch.setenv("EXODUS_ALLOW_LEGACY_EMAIL_CONFIG", "true")
    monkeypatch.setenv("EXODUS_LEGACY_EMAIL_OWNER", "alice")
    cfg = h._get_email_config(owner="alice")
    assert cfg["account_id"] is None
    assert cfg["imap_password"] == "synthetic-legacy-password"
    assert cfg["imap_starttls"] is False
    legacy.assert_called_once_with()


@pytest.mark.parametrize("selected", ["missing", "disabled", "foreign"])
def test_explicit_id_never_switches_to_default_or_legacy(accounts, monkeypatch, selected):
    h, _, add, legacy = accounts
    add("default", default=True)
    add("disabled", enabled=False)
    add("foreign", owner="bob")
    monkeypatch.setenv("EXODUS_ALLOW_LEGACY_EMAIL_CONFIG", "true")
    monkeypatch.setenv("EXODUS_LEGACY_EMAIL_OWNER", "alice")
    with pytest.raises(h.EmailNotConfiguredError, match="unavailable"):
        h._get_email_config(selected, owner="alice")
    legacy.assert_not_called()


def test_existing_encrypted_account_is_preferred_and_unchanged(accounts, monkeypatch):
    from core.database import EmailAccount
    h, factory, add, legacy = accounts
    add("owned", default=True)
    monkeypatch.setenv("EXODUS_ALLOW_LEGACY_EMAIL_CONFIG", "true")
    monkeypatch.setenv("EXODUS_LEGACY_EMAIL_OWNER", "alice")
    with factory() as db:
        before = db.get(EmailAccount, "owned").imap_password
    assert before.startswith("enc:")
    for account_id in (None, "owned"):
        cfg = h._get_email_config(account_id, owner="alice")
        assert cfg["account_id"] == "owned"
        assert cfg["imap_password"] == "synthetic-database-password"
    with factory() as db:
        assert db.get(EmailAccount, "owned").imap_password == before
    legacy.assert_not_called()


def test_database_failure_is_redacted_and_cannot_fallback(accounts, monkeypatch, caplog):
    from core import database
    h, _, _, legacy = accounts
    monkeypatch.setenv("EXODUS_ALLOW_LEGACY_EMAIL_CONFIG", "true")
    monkeypatch.setenv("EXODUS_LEGACY_EMAIL_OWNER", "alice")
    marker = "synthetic-sensitive-driver-value"
    monkeypatch.setattr(database, "SessionLocal", Mock(side_effect=RuntimeError(marker)))
    for action in (lambda: h._get_email_config(owner="alice"), h._list_email_accounts):
        with pytest.raises(h.EmailConfigurationError) as exc:
            action()
        assert marker not in str(exc.value)
    assert marker not in caplog.text
    legacy.assert_not_called()


def test_unreadable_legacy_config_has_redacted_error(accounts, monkeypatch, caplog):
    h, _, _, legacy = accounts
    monkeypatch.setenv("EXODUS_ALLOW_LEGACY_EMAIL_CONFIG", "true")
    monkeypatch.setenv("EXODUS_LEGACY_EMAIL_OWNER", "alice")
    marker = "synthetic-private-settings-value"
    legacy.side_effect = RuntimeError(marker)
    with pytest.raises(h.EmailConfigurationError) as exc:
        h._get_email_config(owner="alice")
    assert marker not in str(exc.value)
    assert marker not in caplog.text


def test_background_empty_list_does_not_read_legacy(accounts):
    h, _, _, legacy = accounts
    assert h._list_email_accounts() == []
    legacy.assert_not_called()


def _migration_settings(monkeypatch, tmp_path, factory, port=993):
    from core import database
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "imap_host": "imap.example.invalid", "imap_port": port,
        "imap_user": "alice@example.invalid", "imap_password": "synthetic-seed-password",
        "smtp_host": "smtp.example.invalid", "smtp_user": "alice@example.invalid",
        "smtp_password": "synthetic-seed-password",
    }))
    monkeypatch.setattr(database, "SETTINGS_FILE", str(path))
    monkeypatch.setattr(database, "engine", factory.kw["bind"])
    return path


@pytest.mark.parametrize("allowed,owner", [("", "alice"), ("false", "alice"), ("true", "")])
def test_startup_does_not_seed_plaintext_without_both_operator_flags(accounts, monkeypatch, tmp_path, allowed, owner):
    from core import database
    _, factory, _, _ = accounts
    path = _migration_settings(monkeypatch, tmp_path, factory)
    before = path.read_bytes()
    monkeypatch.setenv("EXODUS_ALLOW_LEGACY_EMAIL_CONFIG", allowed)
    monkeypatch.setenv("EXODUS_LEGACY_EMAIL_OWNER", owner)
    database._migrate_seed_email_account()
    with factory() as db:
        assert db.query(database.EmailAccount).count() == 0
    assert path.read_bytes() == before


@pytest.mark.parametrize("port,starttls", [(993, False), (143, True)])
def test_opted_in_seed_binds_owner_encrypts_before_insert_and_uses_tls_default(accounts, monkeypatch, tmp_path, port, starttls):
    from core import database
    from src.secret_storage import decrypt
    _, factory, _, _ = accounts
    path = _migration_settings(monkeypatch, tmp_path, factory, port)
    before = path.read_bytes()
    monkeypatch.setenv("EXODUS_ALLOW_LEGACY_EMAIL_CONFIG", "true")
    monkeypatch.setenv("EXODUS_LEGACY_EMAIL_OWNER", "alice")
    database._migrate_seed_email_account()
    with factory() as db:
        row = db.query(database.EmailAccount).one()
        assert row.owner == "alice"
        assert row.imap_starttls is starttls
        assert row.imap_password.startswith("enc:")
        assert row.smtp_password.startswith("enc:")
        assert decrypt(row.imap_password) == "synthetic-seed-password"
        saved_id, ciphertext = row.id, row.imap_password
    database._migrate_seed_email_account()
    with factory() as db:
        row = db.query(database.EmailAccount).one()
        assert (row.id, row.imap_password) == (saved_id, ciphertext)
    assert path.read_bytes() == before


def test_opted_in_seed_does_not_modify_existing_accounts(accounts, monkeypatch, tmp_path):
    from core import database
    _, factory, add, _ = accounts
    add("existing", owner="bob")
    _migration_settings(monkeypatch, tmp_path, factory)
    monkeypatch.setenv("EXODUS_ALLOW_LEGACY_EMAIL_CONFIG", "true")
    monkeypatch.setenv("EXODUS_LEGACY_EMAIL_OWNER", "alice")
    with factory() as db:
        before = db.get(database.EmailAccount, "existing").imap_password
    database._migrate_seed_email_account()
    with factory() as db:
        row = db.query(database.EmailAccount).one()
        assert (row.id, row.owner, row.imap_password) == ("existing", "bob", before)
