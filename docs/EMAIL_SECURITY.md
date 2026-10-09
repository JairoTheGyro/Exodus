# Email credentials and local backups

Use Settings → Email → Email Accounts for a mailbox. Stored account passwords
are encrypted in the local application database with `data/.app_key`. Existing
accounts and ciphertext are preserved by the legacy-config lockdown. No existing
mailbox credentials are deleted or rewritten by this change.

Older versions could silently use plaintext `smtp_password` / `imap_password`
from `data/settings.json`, or `SMTP_PASSWORD` / `IMAP_PASSWORD` environment
variables, when an account lookup failed or found no row. That fallback is now
disabled by default. Database errors fail with a generic configuration error;
they cannot switch the user to a fallback mailbox or expose driver/SQL details.
An explicitly selected missing, disabled or foreign account never selects a
different default account. Encrypted, enabled, owned accounts keep their normal
resolution order.

## Deliberate temporary legacy compatibility

An operator who knowingly depends on the old plaintext fields can temporarily
set **both** of these environment variables on the Exodus process/container:

```text
EXODUS_ALLOW_LEGACY_EMAIL_CONFIG=true
EXODUS_LEGACY_EMAIL_OWNER=the-exact-Exodus-username
```

The named, authenticated owner must match exactly. Anonymous/unscoped calls and
other accounts cannot use the legacy settings, and database failures still fail
closed. Explicit account-ID requests never fall back to legacy settings. The
background account list enumerates saved account rows only.

The old startup import from `settings.json` is also disabled by default. With
both flags deliberately enabled and the accounts table completely empty, that
existing import creates one account for the named owner, encrypting passwords
before insertion. IMAP 993 defaults to implicit TLS; 143 defaults to STARTTLS.
It never modifies existing accounts or erases the old settings file. Environment
variables alone do not create an account. Prefer reconnecting through Email
Accounts instead of relying on this exception. These flags do not encrypt old
settings or environment files; remove the exception after reconnecting.
Do not put passwords in documentation, Git, logs, or chat.

## What to back up

Keep `app.db` and `.app_key` together in a private, consistent local backup.
Without the original key, encrypted credentials cannot be decrypted. Include the
mail cache/attachment directory and configuration if you need that state restored.
See the local backup tool's documented scope before assuming a source-code
backup includes any of these. Git excludes runtime data and credentials.

Cached email bodies and attachments are **not** encrypted by the credential
encryption mechanism. The database key protects credential fields, not the whole
database or data directory. Disk/backup encryption is a separate operator choice.
Do not enable a new cache-encryption scheme without a migration/restore plan.

IMAP and SMTP still require trusted TLS certificates and hostname verification.
The legacy compatibility switch never disables TLS verification. Google OAuth
support requires the separately configured Google OAuth application; Microsoft
OAuth is not implemented. Neither requires or benefits from an LLM.

## Verification

`tests/test_email_legacy_config.py` uses disposable databases and synthetic
credentials to check default denial, explicit owner opt-in, account selection,
encrypted-account preservation, and redacted failures. The existing owner-scope,
SMTP and TLS tests remain separate regression checks. Local certificate fixtures
test rejection of untrusted, expired and wrong-host certificates without sending
mail. A real send/receive test needs an operator-authorized test mailbox; this
patch does not claim that test ran.
