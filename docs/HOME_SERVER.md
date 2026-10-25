# Running Exodus on a home server

This guide moves Exodus from your MacBook to one always-on computer at home,
so family and friends can use it from their own devices. Nothing is opened
to the public internet. People reach it through **Tailscale**, a private
network app, at a private `https://` address.

Your MacBook stays the development machine. Changes still go branch → PR →
merge on GitHub, and the server **pulls** finished updates.

## 1. Pick the computer (your choice)

Exodus itself is light: about 1.3 GB of memory with every service on. Running
AI models on the server is what needs a strong machine.

| Option | Good for |
|---|---|
| A small, quiet mini PC with **16 GB** of memory, running **Ubuntu Server 24.04 LTS** | Exodus with cloud or shared AI, or AI-free. Cheapest to run all day. |
| A **Mac mini** (Apple silicon, 16 GB or more) | Exodus plus small local AI models. Uses Docker Desktop. |
| Keep the **MacBook** | Trying it with one or two people. It only works while the MacBook is on and awake. |

Leave room on the disk for backups: at least 100 GB free.

## 2. Install the basics

On **Ubuntu Server**:

1. Install it with **OpenSSH** turned on, then run `sudo apt update && sudo apt upgrade`.
2. Install **Docker Engine** using Docker's official instructions for Ubuntu
   (docs.docker.com → Install → Ubuntu), then
   `sudo usermod -aG docker $USER` and sign out and back in.
3. Install **git** and **python3**: `sudo apt install git python3`.

On a **Mac mini**: install Docker Desktop, then Xcode Command Line Tools
(`xcode-select --install`) for git.

Then on either:

4. Install **Tailscale** (tailscale.com/download) and run `sudo tailscale up`.
   Sign in with the same Tailscale account your family will join.
5. In the Tailscale admin console, under **DNS**, turn on **MagicDNS** and
   **HTTPS certificates**.

## 3. Get Exodus

The installer downloads Exodus to `~/exodus`, writes `.env`, builds and starts
it, measures the computer for Local AI and sets up one-click updates
(`docs/INSTALL.md`):

```
curl -fsSL https://raw.githubusercontent.com/JairoTheGyro/Exodus/main/install.sh | bash
```

When Tailscale is already set up (step 2), it fills in the phone-alert address
too. At the end it shows the first admin account's temporary password.

To do it by hand instead: `git clone` the repository, `cp .env.example .env`,
then edit `.env`. Always keep `COMPOSE_PROJECT_NAME=sovereign-hub`: the updater
looks for that name. These are the lines that matter for a home server:

```
# The Docker project name the updater expects.
COMPOSE_PROJECT_NAME=sovereign-hub

# Keep the app on the server itself; Tailscale Serve publishes it privately.
APP_BIND=127.0.0.1
APP_PORT=7011

# Sign-in accounts, invitation only (the defaults).
AUTH_ENABLED=true
EXODUS_INVITE_ONLY=true

# Phone alerts through ntfy, published privately by Tailscale Serve (step 4).
NTFY_PUBLIC_URL=https://<server-name>.<tailnet>.ts.net:8443

# Optional: the Services manager (docs/SERVICES_MANAGER.md).
# COMPOSE_FILE=docker-compose.yml:docker-compose.override.yml:docker/service-manager.yml
```

Replace `<server-name>.<tailnet>.ts.net` with the name Tailscale shows for
this computer. Never commit `.env`: it holds secrets and stays on the server.

Start it (the installer does this for you):

```
docker compose up -d
```

The first build takes a while. When it finishes, `docker compose ps` shows the
services as running or healthy.

Let Exodus see this computer's full memory and graphics (Docker only gets part
of them on a Mac or Windows PC). Settings → Account → Local AI and the Cookbook
use it to suggest AI models that fit:

```
python3 scripts/host_hardware.py
```

The updater refreshes it after every update.

## 4. Give it a private HTTPS address

```
sudo tailscale serve --bg 7011
sudo tailscale serve --bg --https=8443 8091
```

- `https://<server-name>.<tailnet>.ts.net` now opens Exodus. Its certificate
  is trusted on every device in your Tailscale network, so invitations and
  phone home-screen installs work.
- Port 8443 is ntfy, for phone alerts.
- Both are reachable **only** from devices signed in to your Tailscale.
- `tailscale serve status` shows what's published. `tailscale serve reset`
  removes it.

## 5. First run

1. Open the address and create the **admin** account. Use a password manager.
2. Settings → System: set the workspace name and logo if you like.
3. Settings → Team & invitations: **invite** each person (choose a username,
   then Create invitation). Send them the link privately, and invite them to
   your Tailscale network too. The link works once and expires after seven
   days (`docs/TEAM_ACCOUNTS.md`).
4. Each person signs in and goes through the **welcome setup**: language,
   their AI, look, email and calendar, and phone alerts. They can add Exodus
   to their phone's home screen (`docs/PHONE_ALERTS.md`).
5. Create a **Family** space in Settings → Account → Spaces
   (`docs/SHARED_SPACES.md`).

## 6. Backups

Exodus data lives in `~/exodus/data` and in Docker volumes. Make a backup now
and on a schedule:

```
python3 scripts/odysseus-backup snapshot
```

Backups go to `~/exodus/backups/`. They are **not encrypted** and contain
keys, so copy them to a second disk or another computer you trust. See
`docs/LOCAL_BACKUPS.md`. On Ubuntu, a daily `cron` entry works:

```
0 3 * * * cd ~/exodus && python3 scripts/odysseus-backup snapshot
```

## 7. Updating the server

**One click:** set up the update helper once, then install tested updates
from Settings → License Tracker → Updates. Exodus checks daily and tells
admins when one is ready. See `docs/UPDATES.md`.

```
python3 scripts/update_agent.py install
```

**By hand:** update the server from its folder:

```
python3 scripts/update_local.py --dry-run   # preview: what would rebuild or reload
python3 scripts/update_local.py             # update
```

The updater:

1. Refuses to run if the folder has local edits or isn't on `main`, and
   only ever fast-forwards from GitHub.
2. **Backs up your data first** with `scripts/odysseus-backup`. Use
   `--no-backup` only if you just made one.
3. Saves a **rollback point**: the current code version, plus a copy of each
   app image it's about to rebuild, tagged `:rollback`.
4. Rebuilds and reloads only the parts that changed, and waits until they're
   healthy. Saved data, `.env` and Docker volumes are never touched.

If something goes wrong:

- **The update stops partway:** fix the cause (for example free disk space)
  and run it again. It picks up where it stopped. A failed update is never
  undone on its own.
- **The new version starts but misbehaves:** go back.

  ```
  python3 scripts/update_local.py --rollback
  ```

  This returns the code to the saved version, puts the `:rollback` image back,
  and reloads the services the update touched. Your saved data is kept. The
  next normal update tries the newer version again.
- **Data itself went wrong:** restore a backup with
  `python3 scripts/odysseus-backup restore <file> --yes`. Stop Exodus first
  (`docker compose stop`); see `docs/LOCAL_BACKUPS.md`.

## Checklist before inviting people

- [ ] Exodus opens at the `https://…ts.net` address from a phone on Tailscale.
- [ ] The admin password is in a password manager, and two-factor sign-in is on
      (Settings → Account → Two-Factor Authentication).
- [ ] A backup was made and copied off the server.
- [ ] Phone alerts: Settings → Account → Phone alerts → Send test arrives.
- [ ] `python3 scripts/update_local.py --dry-run` says the server is up to date.
