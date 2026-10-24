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
