# Vaultwarden in Exodus

Home → Vaultwarden and Privacy Hub → Vaultwarden open the same management panel
in Full and AI-Free modes. It checks the vault and gateway independently. **Open
vault** goes through Exodus's authenticated `/vault` launch route to
`http://localhost:8092/vault/` on this Mac. Sign in with a separate Vaultwarden
account and master password. Exodus does not see vault items or login secrets.
If a Bitwarden client previously used the root address on port 8092, update its
server URL to include `/vault`; its existing vault data stays in the same volume.

## Current local deployment

- Official `vaultwarden/server:latest`, with `pull_policy: missing` so ordinary
  starts do not fetch a new version. Verified 2026-10-01 against server 1.37.3,
  digest `sha256:1587c45feaa479f1f5e8af3b00eded36bff77bcf1880cf8dbf0541706dd470e0`.
  The web-vault frontend reports its own separate version.
- Existing `sovereign-hub_vaultwarden-data` volume is mounted at
  `/data/vaultwarden`, with `DATA_FOLDER` matching. No existing data is copied
  into a second live vault or deleted.
- Non-root UID/GID 1000, read-only root filesystem, bounded temporary directory,
  dropped capabilities, no-new-privileges, process limits and health checks.
- Caddy gateway publishes **127.0.0.1:8092 only**. The vault itself publishes no
  host port and runs on an internal bridge with no Internet egress. The gateway
  retains only NET_BIND_SERVICE because the official Caddy binary has that file
  capability. Exodus can ping health on that bridge; it has no vault/secret mounts.
- `SIGNUPS_ALLOWED=false`; accounts require an administrator invitation. No SMTP
  or external push provider is configured. `ENABLE_WEBSOCKET=true` enables local
  notification delivery on the normal service port; legacy port 3012 is unused.
- Icon downloading and mobile push are disabled. Vault request logging is disabled
  at the gateway to avoid recording notification access tokens in query strings.
- The gateway preserves upstream CSP, SAMEORIGIN and other response protections.
  Cross-origin iframes are deliberately blocked; opening the separate vault page
  preserves those protections and isolates its browser storage from Exodus.
  Only the native `VW_ADMIN` cookie is forwarded to the vault; localhost cookies
  otherwise cross port boundaries, so Exodus's session cookie must be discarded.

Localhost HTTP is a browser-secure context for Web Crypto, **not HTTPS encryption**.
Keep the host binding on loopback. Do not expose this HTTP port to a LAN or the
Internet. The optional TLS configuration below requires a trusted certificate.
This integration is not an independent security audit or production certification.
The workspace's existing demo-only/no-private-data notice remains applicable.

## Prepare, start and check

From this repository directory:

```sh
python3 scripts/prepare_vaultwarden.py
docker compose -p sovereign-hub up -d --no-deps vaultwarden vaultwarden-gateway
docker compose -p sovereign-hub up -d --no-deps --no-build odysseus
```

The preparation script stops only the vault, makes a consistent private backup
of its complete data volume, fixes ownership and provisions the admin credential
only if absent. Missing, empty or unreadable admin-token files prevent the vault
from starting; interrupted preparation reuses its private password safely.
Preparation intentionally leaves the vault stopped for the
following start step; failures attempt to restart the previous container.
The ordinary UI diagnostic start command is for an already-prepared installation.
After source edits the development Compose override mounts the new route files;
a container recreation is necessary the first time these mounts are added.
Fresh installations build Exodus with the normal Compose build first.

The admin **password** is stored privately at
`data/vaultwarden-access/sovereign-hub-admin-password.txt` (owner-only permissions).
The running vault receives only its Argon2id **hash**, through
`ADMIN_TOKEN_FILE=/run/secrets/vaultwarden_admin_token` in the dedicated
`sovereign-hub_vaultwarden-secrets` volume. Exodus receives neither. Do not paste
this password into chat, commit it, or use it as a user's master password.
Existing credentials are never silently rotated by preparation.

The native admin page is `http://localhost:8092/vault/admin`. Use its invitation
controls to onboard a vault account; leave public registration closed. With no
SMTP service, use Vaultwarden's local invitation workflow. The public client
configuration can still show a registration action so invited users can finish
onboarding; uninvited registrations are rejected by the server.
Vaultwarden's own admin settings can override environment defaults, so changes
there must be reviewed deliberately. Exodus's config endpoint describes the
shipped deployment defaults, not an audit of later native admin settings.

## Health versus sync

`GET /api/vaultwarden/status` and `/api/vaultwarden/config` require an Exodus
browser session and are available in both modes. Checks have a three-second
network budget, reject redirects and unsafe target settings, do not follow
system HTTP proxies, and return no secret values or raw upstream errors.

`/vault/alive` checks Vaultwarden's server/database availability. Exodus reports
`running` only if both vault and gateway pass; `offline` or `degraded` explains a
failure. **Device sync stays unknown** until the user verifies it in the vault.
No credentials are borrowed to manufacture a successful sync indicator.

## Optional HTTPS on this Mac

The separate `docker-compose.vaultwarden-tls.yml` overlay uses the same loopback
port and vault data. Put a certificate valid for `localhost` (with its full
chain) and its matching private key in `data/vaultwarden-tls/cert.pem` and
`data/vaultwarden-tls/key.pem`. The key must be readable by container UID 1000;
protect the enclosing host directory and never commit it. The browser must trust
the issuer; do not bypass certificate warnings. No CA is installed automatically.

Set `VAULTWARDEN_DOMAIN=https://localhost:8092/vault` in the ignored local `.env`
(or supply that value in the shell), then use all three files:

```sh
docker compose -p sovereign-hub -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.vaultwarden-tls.yml up -d --no-deps vaultwarden vaultwarden-gateway odysseus
```

The overlay adds HTTPS and preserves the upstream CSP. It sends HSTS max-age=0
on localhost so a host-wide policy cannot break other local HTTP apps. Its separate internal
health listener serves only the alive route and is not published to the host.
Remote/domain deployment is a separate task: provision trusted certificates,
firewalling and operator access deliberately rather than widening this binding.

## Backup and upgrades

Backups made by preparation are under ignored `backups/vaultwarden/`. They contain
sensitive vault database, attachments and encryption keys; protect them just like
the vault. The admin password and secret volume require their own private backup.
GitHub backs up source code, **not** these local volumes or credentials. Never run
`docker compose down -v` on the real project.

Before pulling a newer `latest`, stop the vault and back up the whole data volume,
retain the prior image digest, and test restoration into a separate disposable
volume. Database migrations may prevent downgrading: restore the matching backup
with the old image rather than running an older binary against upgraded data.
Check release notes and update the License Tracker's recorded version after an
intentional upgrade. The current used-version record remains 1.37.3.

## Verification

- `python3 tests/test_prepare_vaultwarden.py`: interrupted setup recovery and
  rejection of insecure password-file permissions.
- `tests/vaultwarden_integration.py`: isolated auth, both modes, health, timeout,
  URL validation, no leaked secrets, gateway failure, safe configuration.
- `tests/helpers/test_vaultwarden_ui.mjs`: launcher, offline/degraded states,
  browser origin checks, cancellation, link preference and honest sync wording.
- `python3 tests/vaultwarden_e2e.py`: actual disposable Compose containers,
  loopback binding, hardening, persistent volume recreation, routing, CSP,
  WebSocket handshakes, registration rejection and outage recovery.
- `python3 tests/vaultwarden_tls.py`: disposable certificates and containers,
  verified TLS connection and certificate rejection, HSTS and framing headers.

Test containers never mount the real vault, use real credentials or send email.
An actual signed-in password save/sync is a separate user validation step.

References: [Vaultwarden proxy setup](https://github.com/dani-garcia/vaultwarden/wiki/Proxy-examples),
[admin token protection](https://github.com/dani-garcia/vaultwarden/wiki/Enabling-admin-page),
[WebSocket notifications](https://github.com/dani-garcia/vaultwarden/wiki/Enabling-WebSocket-notifications),
[HTTPS](https://github.com/dani-garcia/vaultwarden/wiki/Enabling-HTTPS).
