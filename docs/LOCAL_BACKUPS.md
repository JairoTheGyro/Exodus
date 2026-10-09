# Local Exodus data backups

GitHub stores source code. The local backup command protects the data Git ignores:
notes, accounts/settings, calendar files, Library uploads, scratchpad text and
revision metadata, mail cache, and the active `data/vaultwarden` directory
including its database, attachments and vault keys. It also includes `.app_key`,
which decrypts saved credentials, and the private TLS and admin-password files
under `data/`. Notes themselves are not encrypted. Run this
on the Mac host: Exodus deliberately cannot read the vault's private mounts.

This extends the existing `scripts/odysseus-backup`; it adds no container, model,
cloud upload or always-running Python process. It works independently of either
Exodus workspace mode.

## What a snapshot guarantees

- `.db`, `.sqlite` and `.sqlite3` files use SQLite's read-only backup API and an
  integrity check. WAL commits are included; corresponding journal/SHM/WAL files
  are not restored on top of the finished snapshot. A failed database snapshot
  aborts the archive instead of falling back to a potentially corrupt raw copy.
- Regular files are streamed, not loaded into memory. A file changing while it
  is copied fails the snapshot. File and directory symlinks are skipped.
- A completed archive appears atomically and cannot replace an existing file.
  Archives and restored files are owner-only (`0600`); private directories use
  `0700`. The source files are not edited. The archive preserves file timestamps.
- This is a consistent snapshot **per SQLite database**, not a transaction across
  every database and attachment. Stop applications that write these files before
  a major migration/restore or when an exactly coordinated snapshot is needed.
- The archive is **not encrypted**. It contains credentials and decryption keys.
  It remains on this Mac, so it does not protect against losing the Mac or its
  disk. Copying it to another device requires a separate deliberate secure plan.

The command backs up the checkout's `data/` directory. Docker named volumes
(`chromadb-data`, `ntfy-cache`, `harness-home`, and the separate admin-token hash
volume), external/custom storage paths, and system Keychain trust are not included.
The retained private admin-password file allows the preparation script to rebuild
the admin-token hash when its secret volume is missing. Chroma's vector store
needs its own stopped-volume backup if preserving the existing vectors matters.
The old Vaultwarden named volume is rollback history; the current bind directory
is the vault data included here. Cached research runs are excluded by default.

## Manual snapshot and verification

From the Exodus repository on the Mac:

```sh
python3 scripts/odysseus-backup snapshot --include-env --include-attachments
python3 scripts/odysseus-backup list
python3 scripts/odysseus-backup verify '/absolute/path/to/the/returned-backup.tar.gz'
```

`--include-env` includes the local `.env` only by explicit choice. It never prints
its values. `--include-attachments` includes the re-downloadable mail attachment
cache. `--include-research` additionally includes large research run files.

The optional `--keep 3` removes older archives bearing this updated command's
exact timestamped filename pattern, only after a new snapshot succeeds. It does
not touch old manual filenames, Vaultwarden migration archives, subdirectories,
or other files. Without `--keep`, no archive is deleted. Custom `--out` filenames
cannot be combined with automatic retention.

## Daily backup on this Mac

Preview the configuration first; it writes nothing:

```sh
python3 scripts/setup_local_backups.py
```

After approval, install/load the per-user macOS job:

```sh
python3 scripts/setup_local_backups.py --install
```

The installer records that Python executable's absolute path and the existing
checkout path, including spaces. It creates
`~/Library/LaunchAgents/local.exodus.backup.plist` with owner-only permissions and
loads it through `launchctl`. A different existing job is never replaced.

The job runs daily at **03:00 local time**, retains the newest **three** generated
archives in `backups/`, and includes `.env` and cached mail attachments. It does
not run immediately on installation or login. It is a user job and requires that
Mac account to be logged in. macOS may defer a calendar job missed during sleep
until wake; it is not an uptime guarantee. Check the actual successful backup
files and the owner-only `backups/automation/backup.log` and `backup-error.log`.
A changed checkout/Python path requires deliberately updating the job.

To inspect or stop the schedule (this keeps existing backups):

```sh
launchctl print "gui/$(id -u)/local.exodus.backup"
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/local.exodus.backup.plist"
```

Delete that exact plist only if permanently removing the schedule; otherwise
macOS can load it again on the next login.

Apple's [launchd documentation](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)
describes per-user jobs, calendar intervals and their permissions.

## Restore carefully

First stop Exodus, Vaultwarden and any other writers that use the restored files.
Verify the chosen archive. Never test restoration against real user data.

```sh
python3 scripts/odysseus-backup verify '/absolute/path/to/backup.tar.gz'
python3 scripts/odysseus-backup restore '/absolute/path/to/backup.tar.gz' --yes
```

Restore fully extracts into a private temporary directory before swapping in the
new `data/`. It keeps the previous data as `data.before-restore-<timestamp>` and
rejects traversal paths, links, duplicate names and special files. A failed
extraction leaves the current data in place. Existing `.env` is preserved unless
`--restore-env` is explicitly added. With that option, the archive must contain
`.env`, and the old file is retained as `.env.before-restore-<timestamp>`.

After a restore, confirm Docker's service user can read/write the restored bind
mounts before starting services. Vault preparation can restore its required
ownership and secret-volume hash. System certificate trust is a separate Mac
setting. Log in and check a note, calendar entry, Library file and vault item;
never infer device sync from the health indicator alone.

The separate JSON export in Settings is a selective export of application
settings/memories/skills. It is useful, but is not a full database/file backup.

## Automated verification

`tests/test_local_backup_roundtrip.py` uses synthetic SQLite databases with live
WAL data and synthetic key/credential files, then restores to disposable paths.
It covers files, scratchpad metadata, vault attachments/keys, permissions,
retention, optional environment restoration, failure cleanup, corruption,
symlinks, timestamp preservation and streaming memory use.
`tests/test_local_backup_schedule.py` verifies the exact plist, safe paths with
spaces, no immediate run, refusal to overwrite another job, and launch failure
cleanup without calling real `launchctl`. Existing CLI traversal tests remain.
