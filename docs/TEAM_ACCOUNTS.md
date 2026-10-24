# Team accounts and invitations

Exodus uses one first-run administrator and invitation-only member onboarding.
Existing accounts, passwords, roles and content are retained. Further administrators
can be appointed deliberately using the existing role controls. Invitations create
regular members only; the recipient chooses their own password.

## Persistence and rollback (before deployment)

The auth.json format gains an additive `invitations` map and `retired_usernames`
list. No SQL schema migration is needed. Invitations store only SHA-256 token
hashes, a selected username, creator and expiry; never the raw invitation link.
Account creation and consuming the invitation use one atomic auth.json write.
The supported deployment is one Exodus application process; do not start several
workers writing the same JSON files. Preferences use the existing per-owner map.

Before deploying, copy auth.json and user_prefs.json (when present) to a private,
ignored backup directory, retaining permissions. To roll back, stop Exodus and
restore those files together with the corresponding source version. A rollback
can remove accounts/invitations created after the backup; do not overwrite newer
state casually. Never commit auth, session, preference, or vault files to Git.

## Administrator workflow

Settings → Team & invitations → choose a username → Create invitation → copy
its link privately to that person. The link is a single-use bearer credential,
expires after seven days, and can be revoked. The token lives in the URL fragment,
not an HTTP query or server log. Anyone with that link can claim that username:
this is not email verification. No email is sent automatically.

The default `EXODUS_INVITE_ONLY=true` rejects public signup even if legacy
signup_enabled was on. An operator can explicitly set it false to restore the
legacy open-registration controls; the ordinary team UI cannot disable policy.
Team mode requires authentication and prohibits localhost authentication bypass.
Existing direct administrator account provisioning remains under Advanced in the
Team panel; invitations are the recommended path so administrators don't choose
teammates' passwords. Removed/renamed usernames are retired to prevent a new
member inheriting records that still reference an old username.

## Welcome setup for new people

The first time a new account opens Exodus, a short **welcome setup** walks
through:

1. language;
2. their AI: shared AI, their own cloud account, or no AI (see below);
3. the look of the built-in apps;
4. connecting email and a calendar (optional; opens Settings);
5. phone alerts (their private ntfy topic);
6. done.

Every step can be skipped, and everything can be changed later in Settings.
It shows once per account. "Skip setup" or Escape also count. Anyone can run
it again from Settings → Account → **Welcome setup**. Accounts that had
already chosen their workspace before this existed don't see it
automatically.

## Your AI and spending caps

Settings → Account → **Your AI** lets each person choose:

- **Shared AI:** the AI connections the admin added for everyone. Nothing to
  set up.
- **My own cloud account:** choose a provider (OpenRouter, OpenAI, Anthropic,
  Google Gemini, DeepSeek, Groq, xAI or NVIDIA), paste their API key and press
  Connect. The account is private to them, the key is stored encrypted and
  never shown again, and they pay that provider directly. Members can't type a
  web address, so an account can't point at the home network or Exodus's
  internal services. Only the admin connects local or self-hosted models, in
  Settings → Added Models (`docs/LOCAL_AI.md`).
- **No AI:** turns on AI-free mode for their account only.

**Monthly spending cap.** Each person can set a cap in dollars. An admin can
also set a cap for any member under "Everyone's AI spending", and the member
can't raise it. The lower cap applies. When the month's estimated cost
reaches the cap, AI pauses for that person until the 1st of the next month
(UTC), or until the cap is raised. Everything else keeps working.

How cost is counted:

- Chat and agent turns are counted, using the provider's reported cost or an
  estimate from `src/model_pricing.py`.
- AI running on your own computers counts as $0.
- Costs are estimates, so keep the provider's own limits too.

**After updating:** spending counts start once the app image is rebuilt
(`routes/chat_helpers.py` is part of the image).

## Personal and shared configuration

Themes, personal preferences, Home layout/AI mode, notes, documents, calendar
accounts/events, and mail accounts retain their owner-scoped stores. Shared server
addresses, container configuration, tool availability and explicitly shared model
connections remain administrator-managed installation configuration. Shared
announcements and model resources are not private personal records.

Vaultwarden has a separate login/master password per person. Exodus must never
copy an administrator's vault session into a member account. Private vault items
stay in Vaultwarden; organization collections control explicitly shared items.
The legacy optional administrator-only Bitwarden CLI integration uses owner-specific config and
CLI data directories for every named user; the old vault.json is retained but is
not inherited by named accounts. Reconnect any previously configured CLI account. Renaming an Exodus username
also requires reconnecting its optional CLI account; the old private directory
is retained and cannot be claimed by another user. This does not rename or
change the independent Vaultwarden web account.

## Vaultwarden onboarding and offboarding

Public vault registration is disabled; invitations remain enabled. Open the
separate Vaultwarden administration page and invite the first owner's email,
then invite each teammate (or use an organization's invitation flow). With no
SMTP configured, recipients can open the vault signup page and use exactly the
invited email. Set the master password only in the Vaultwarden interface.
Exodus provides links and guidance, not a fake automatic account connection.
The Vaultwarden administrator credential remains outside the Exodus container.

Removing an Exodus user revokes their Exodus sessions/tokens. Separately revoke
that person's Vaultwarden sessions/access and organization memberships in
Vaultwarden. Review other external service access too. Exodus logout cannot log
out a different-origin vault browser session: on a shared computer log out of
both, or use separate browser profiles.

Current deployment remains Mac-only. Invitation links and service URLs are usable
only on that Mac until a shared trusted HTTPS deployment is configured. SearXNG
is a shared search engine, Chroma is a backend with application owner filters,
each account sends its ntfy alerts to its own private topic (see
`docs/PHONE_ALERTS.md`; the topic name is the only secret), and Harness is
admin-only. These services are not automatically converted into separate tenant
instances by adding Exodus accounts. Do not publish their local ports. Every future integration must document personal ownership,
shared settings, onboarding, offboarding, and isolation tests in both modes.

Official invitation behavior:
https://github.com/dani-garcia/vaultwarden/wiki/Disable-registration-of-new-users


## Verification

`tests/team_accounts_integration.py` covers invitations, real password hashing,
replay/expiry/revocation, concurrent acceptance, persistence failures, role gates,
retired usernames, concurrent personal preferences, both AI modes, and isolated
vault CLI environments. Run it standalone or select `team-accounts` in the
existing local test runner. `tests/team_accounts_fixture.py` serves the real UI
against disposable stores for browser invitation acceptance. Use a different
browser hostname/profile from the real installation: cookies are not port-scoped.
No real teammate accounts, emails, vault passwords or credentials are needed.

First-run setup fails closed when an existing account file cannot be decoded;
a corrupt account store must not reopen the initial administrator signup screen.
