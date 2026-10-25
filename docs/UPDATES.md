# Updates

Exodus checks for new versions once a day. When a newer version has
**passed all of its automatic tests** on GitHub, admins get a notification
(in Exodus and on their phone, if phone alerts are set up). You choose when
to install it.

## Install an update

1. Open **Settings → License Tracker → Updates** (admins).
2. It shows the version this server runs, the newest version, whether it
   passed its tests, and what's new.
3. Press **Update now** and confirm.

Exodus then:

- backs up your data;
- keeps a copy of the current version so you can go back;
- downloads the update, rebuilds what changed and restarts.

It takes a few minutes, and Exodus may be unavailable briefly. The card shows
the progress, then **Exodus is up to date. Reload the page.**

**Update now** only appears for a version whose tests all passed. If GitHub
changes between your click and the install, nothing is changed: check again
and approve the newer version.

## One-time setup: the update helper

Exodus runs inside Docker, which can't update itself. A small helper on the
server does it for you. Set it up once, on the server, from the Exodus folder:

```
python3 scripts/update_agent.py install
```

- **Mac:** it starts now and at every login (a LaunchAgent). Log:
  `~/Library/Logs/exodus-update-helper.log`.
- **Linux:** it runs as a systemd user service. To keep it running when
  nobody is logged in, run once: `sudo loginctl enable-linger "$USER"`.
  Log: `journalctl --user -u exodus-update-helper`.
- **Windows:** not available; update by hand (below).

Check on it with `python3 scripts/update_agent.py status`, and remove it with
`python3 scripts/update_agent.py uninstall`.

The helper only does one thing: when an admin approves an update in Exodus,
it runs the normal updater for that exact version. It doesn't listen on the
network; it reads and writes small files in `data/exodus-update/`. It only
installs the official Exodus `main` branch from GitHub, never anything else.

## Update by hand

Without the helper, or on Windows, run on the server, from the Exodus
folder:

```
python3 scripts/update_local.py --dry-run   # preview
python3 scripts/update_local.py             # update
```

It does the same backup and rollback steps. See `docs/HOME_SERVER.md`.

## If something goes wrong

- **The update stopped:** the card shows why. Fix the cause (for example,
  free disk space) and press **Update now** again.
- **The new version misbehaves:** on the server, run
  `python3 scripts/update_local.py --rollback`. Your data is kept.
- **Data went wrong:** restore the backup made before the update
  (`docs/LOCAL_BACKUPS.md`).

## Turn off the daily check

Set `EXODUS_UPDATE_CHECKS=false` in `.env` and restart Exodus. You can still
press **Check for updates** in the Updates card.
