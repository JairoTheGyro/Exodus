# Install Exodus

One command sets up Exodus on a Mac or a Linux computer.

## Before you start

- **Docker**, running: Docker Desktop on a Mac, Docker Engine on Linux
  (docs.docker.com → Install). On Linux, also run
  `sudo usermod -aG docker "$USER"`, then sign out and back in.
- **git** and **python3**: on a Mac, `xcode-select --install`; on Ubuntu,
  `sudo apt install git python3`.
- About **20 GB** of free disk space for the first build.
- Optional: **Tailscale**, to reach Exodus privately from your other devices
  (`docs/HOME_SERVER.md`).

## Install

```
curl -fsSL https://raw.githubusercontent.com/JairoTheGyro/Exodus/main/install.sh | bash
```

This downloads Exodus to `~/exodus` (set `EXODUS_DIR` to choose another
folder). If you already downloaded Exodus, run `./install.sh` inside its
folder instead.

The installer:

1. checks Docker is installed and running, and explains what to do if not;
2. creates the settings file `.env`:
   - invitation-only sign-in;
   - Exodus reachable only from this computer (Tailscale publishes it
     privately);
   - a free port, 7011 or the next free one;
   - the name the updater expects;
3. builds and starts Exodus, and waits until it's healthy. **The first build
   takes 20–60 minutes;**
4. measures this computer's memory, so Local AI suggests models that fit;
5. asks whether to set up **one-click updates** (the update helper,
   `docs/UPDATES.md`). The answer is yes unless you say no;
6. shows the address to open and, on a brand-new install, the first admin
   account's **temporary password**. Sign in and change it right away in
   Settings → Account.

Options (after `bash -s --` when piping, or after `./install.sh`):

| Option | Does |
|---|---|
| `--dry-run` | Only shows what would happen. Changes nothing. |
| `--port 7020` | Uses another port. |
| `--no-start` | Prepares the settings without building or starting. |
| `--with-helper` / `--no-helper` | Sets up the update helper, or not, without asking. |

## Running it again

It's safe. Your `.env` is kept: only missing essentials are added. Exodus is
rebuilt and restarted. To update later, use **Update now** in Settings →
License Tracker → Updates, or `python3 scripts/update_local.py`.

## If it stops

The message says what to do. The usual ones:

- **Docker is not running:** start Docker (Desktop) and wait until it's ready.
- **Docker refused access** (Linux): add yourself to the `docker` group, as
  above.
- **The build failed:** often low disk space. Free some and run it again.

Windows isn't supported by the installer yet; follow `docs/HOME_SERVER.md`
by hand.
