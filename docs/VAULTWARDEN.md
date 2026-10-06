# Vaultwarden in Exodus

Home and Privacy Hub use the same Vaultwarden launcher in Full and AI-Free mode.
The authenticated Exodus `/vault` route opens **https://127.0.0.1:8092/** in the
chosen tab. The vault has its own account and master password. A vault account
is separate from the existing Vaultwarden admin-console token.

## One local container

The official `vaultwarden/server:latest` image now serves HTTPS directly using
Rocket TLS. Caddy is no longer a service. Ordinary starts use `pull_policy: missing`
and retain the installed server 1.37.3 / Web Vault 2026.7.0 image; this change does
not upgrade the vault database. The binding is `127.0.0.1:8092:80`; SearXNG keeps
8080. A normal dedicated bridge connects Exodus and the vault because Docker
Desktop does not publish a usable host port from an internal-only bridge.

The container stays non-root, has a read-only root filesystem, drops capabilities,
and retains process limits, no-new-privileges and a bounded temporary directory.
The network permits egress, but icon downloads, mobile push and update checks
remain disabled. No SMTP or external notification provider is added. WebSocket
notifications use the same HTTPS port. Native CSP and SAMEORIGIN remain intact;
the vault opens on its own origin rather than inside an iframe.

Current web-vault API validation requires HTTPS even when localhost provides a
browser secure context. Changing a plain HTTP port does not fix registration.
Rocket also sends HSTS for HTTPS responses. Use the **127.0.0.1** URL: an IP
literal cannot become an HSTS host, avoiding a policy that upgrades unrelated
HTTP applications on `localhost`. The former proxy's cookie filtering is gone;
ports do not isolate same-host cookies. Use Exodus's usual `localhost:7070`
address and the vault's `127.0.0.1:8092` address for separate host-only cookies.

## Data and preparation

The live vault is a host bind mount: `./data/vaultwarden:/data`, with
`DATA_FOLDER=/data`. Preparation stops only Vaultwarden, archives the old named
volume consistently, validates copied files and SQLite integrity, then migrates
into the initially empty bind directory. The old named volume remains untouched
for rollback; subsequent preparations back up the active bind directory and do
not recopy stale volume data. Nothing removes a volume. Do not run `down -v`.

`data/vaultwarden-tls` contains a one-year self-signed **leaf certificate**, not a
new certificate authority. It covers `127.0.0.1`, `localhost` and the Docker-only
`vaultwarden` name. Its directory is private; only exact certificate/key files
are mounted read-only into Vaultwarden. Exodus receives only the public
certificate, using strict certificate and hostname validation for `/alive`.
Empty private overlays mask vault files, TLS keys and admin credentials under
both of Exodus's existing data mounts.

The existing admin secret volume and Argon2 hash remain unchanged. Its private
password file stays in `data/vaultwarden-access`; never use it as a vault master
password. All vault data, TLS keys, secret files and `backups/vaultwarden` stay
outside Git and Docker image builds.

```sh
python3 scripts/prepare_vaultwarden.py
docker compose -p sovereign-hub up -d --no-deps vaultwarden
docker compose -p sovereign-hub up -d --no-deps --no-build odysseus
```

Preparation never installs browser/OS trust. It retains existing valid keys and
rejects incomplete, mismatched or expiring certificate files. Certificate renewal
is an explicit operator action. Custom `VAULTWARDEN_DATA_DIR`/`VAULTWARDEN_TLS_DIR`
Compose locations must also be passed as `--data-dir`/`--tls-dir` to preparation.
The old TLS overlay filename remains as an optional compatibility file; it adds
no container and is no longer necessary.

## One-time trust and initial signup on this Mac

After checking the prepared certificate, the operator can trust this specific
certificate for SSL in their login keychain. From the repository:

```sh
security add-trusted-cert -r trustRoot -p ssl \
  -k "$HOME/Library/Keychains/login.keychain-db" data/vaultwarden-tls/cert.pem
```

This is a deliberate user action; it may ask for Mac authentication. Do not
bypass a browser certificate warning. Reload/reopen the vault after trusting it.
Creating the actual account and entering a master password are user actions.
Do not add a `-s` hostname restriction to this trust command: Chromium skips
policy-string-constrained macOS trust settings. Standard certificate hostname
validation still applies to the certificate’s three local names.

The local deployment now uses `VAULTWARDEN_SIGNUPS_ALLOWED=false` and
`INVITATIONS_ALLOWED=true`. The separate vault administrator invites the first
owner's email and subsequent team members. Without SMTP, the invited person opens
`/#/signup` and uses that exact email to create their own vault/master password.
Settings → Team & invitations links to the vault administration page. Exodus
invitations do not create vault accounts automatically. See TEAM_ACCOUNTS.md for
the complete onboarding/offboarding procedure. Native admin settings can override
environment defaults; Exodus labels the value as deployment policy.
The first ordinary vault account does not replace or grant admin-console access.

## Health and verification

`/api/vaultwarden/status` verifies the direct TLS `/alive` endpoint within three
seconds. `/api/vaultwarden/config` exposes only safe launch and deployment values.
Both require Exodus authentication and work in both modes. There is no Docker
socket or vault credential supplied to Exodus. Health proves service/database
reachability; device sync remains unknown until tested inside a signed-in vault.

Tests use disposable data, certificates and Docker resources:

- `tests/test_prepare_vaultwarden.py`: safe migration, retries and certificates.
- `tests/vaultwarden_integration.py`: both modes, auth, timeouts, strict TLS and
  safe configuration/error responses.
- `tests/helpers/test_vaultwarden_ui.mjs`: launcher, onboarding, tab preference
  and local/remote address handling.
- `tests/vaultwarden_e2e.py` and `tests/vaultwarden_tls.py`: the actual official
  container, loopback binding, verified TLS, registration policy, persistence,
  native response protections and optional overlay compatibility.

On 2026-10-01 the focused verification passed 17 preparation, 14 backend,
8 container E2E and 3 TLS-overlay tests, plus the JavaScript launcher checks.
After the operator trusted the prepared certificate, the in-app browser opened
the live login and Create account pages without a certificate warning. Signup
preflight was tested in disposable data with registration both enabled and
disabled; no real user account or master password was created by these tests.

Back up the full active bind directory only while stopped, along with the secret
volume/admin password and TLS files. To roll back this storage transition, stop
the new vault, restore the previous Compose configuration and use the retained
named volume with the previous image. Changes made after migration exist only
in the active bind directory; preserve those before any rollback.

References: [HTTPS and Rocket TLS](https://github.com/dani-garcia/vaultwarden/wiki/Enabling-HTTPS),
[HTTP localhost registration limitation](https://github.com/dani-garcia/vaultwarden/discussions/6883),
[HSTS host scope](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Strict-Transport-Security),
[admin token protection](https://github.com/dani-garcia/vaultwarden/wiki/Enabling-admin-page).
