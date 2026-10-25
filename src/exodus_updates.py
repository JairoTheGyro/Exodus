"""Exodus one-click updates: find tested updates, let an admin approve one.

Exodus runs inside Docker and can't update itself. A small helper on the
server (scripts/update_agent.py, outside Docker) does the update with
scripts/update_local.py, which backs up data first, keeps a rollback image,
and only fast-forwards to the official JairoTheGyro/Exodus main branch.

They talk through files in DATA_DIR/exodus-update/:
  installed.json  helper → app   revision running on the server
  helper.json     helper → app   heartbeat ("the helper is set up and running")
  request.json    app → helper   the update an admin approved
  status.json     helper → app   progress and result of that update
  check.json      app only       last GitHub check, and who was notified

"Tested" means every GitHub check on that revision finished without failing.
An approval names one exact revision; the updater refuses if GitHub's main
branch moved after the approval.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from core.atomic_io import atomic_write_json

REPOSITORY = "JairoTheGyro/Exodus"
BRANCH = "main"
SHA = re.compile(r"[0-9a-f]{40}")
MAX_RESPONSE = 4_000_000
HELPER_FRESH = timedelta(minutes=3)
REQUEST_TTL = timedelta(hours=1)
CHECK_EVERY = timedelta(hours=24)
MIN_MANUAL_GAP = timedelta(seconds=60)
PASSING = {"success", "neutral", "skipped"}
FAILING = {"failure", "cancelled", "timed_out", "action_required", "startup_failure", "stale"}
# Jobs that publish things (the website, images) say nothing about whether
# Exodus works, so they don't decide "tested".
NOT_A_TEST = re.compile(r"deploy|pages|static site|publish|release", re.I)


class UpdateError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _parse_time(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _text(value, limit=300) -> str:
    return " ".join(str(value or "").split())[:limit]


def update_dir() -> Path:
    from src.constants import DATA_DIR
    return Path(DATA_DIR) / "exodus-update"


def _read(name: str, folder: Path | None = None) -> dict:
    path = (folder or update_dir()) / name
    try:
        if path.stat().st_size > 1_000_000:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(name: str, data: dict, folder: Path | None = None) -> None:
    folder = folder or update_dir()
    folder.mkdir(parents=True, exist_ok=True)
    atomic_write_json(str(folder / name), data)


def installed(folder: Path | None = None) -> dict:
    data = _read("installed.json", folder)
    revision = str(data.get("revision") or "")
    if not SHA.fullmatch(revision):
        return {}
    return {"revision": revision, "recorded_at": _text(data.get("recorded_at"), 40)}


def helper(folder: Path | None = None, now: datetime | None = None) -> dict:
    data = _read("helper.json", folder)
    seen = _parse_time(data.get("seen_at"))
    online = bool(seen and (now or _now()) - seen < HELPER_FRESH)
    return {"online": online, "seen_at": _iso(seen) if seen else None, "platform": _text(data.get("platform"), 40)}


def status(folder: Path | None = None) -> dict:
    data = _read("status.json", folder)
    state = data.get("state")
    if state not in {"pending", "running", "done", "failed"}:
        return {}
    return {
        "state": state,
        "id": _text(data.get("id"), 64),
        "target": data.get("target") if SHA.fullmatch(str(data.get("target") or "")) else None,
        "message": _text(data.get("message"), 500),
        "log": [_text(line, 300) for line in (data.get("log") or [])[-30:] if isinstance(line, str)],
        "started_at": _text(data.get("started_at"), 40) or None,
        "finished_at": _text(data.get("finished_at"), 40) or None,
    }


def _tested(runs: list[dict]) -> str:
    if not runs:
        return "unknown"
    if any(r.get("conclusion") in FAILING for r in runs):
        return "failed"
    if all(r.get("status") == "completed" and r.get("conclusion") in PASSING for r in runs):
        return "passed"
    return "testing"


class Updates:
    def __init__(self, folder: Path | None = None, transport=None):
        self._folder = folder
        self.transport = transport
        self.lock = asyncio.Lock()

    @property
    def folder(self) -> Path:
        return self._folder or update_dir()

    def client(self):
        return httpx.AsyncClient(timeout=15, follow_redirects=False, transport=self.transport,
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "Exodus-Updates",
                                          "X-GitHub-Api-Version": "2022-11-28"})

    async def github(self, client, suffix: str, params=None):
        url = f"https://api.github.com/repos/{REPOSITORY}{suffix}"
        try:
            async with client.stream("GET", url, params=params) as response:
                if response.status_code in (403, 429):
                    raise UpdateError("GitHub is limiting requests right now. Try again later.")
                if response.status_code == 404:
                    raise UpdateError("GitHub could not find that revision.")
                if response.status_code != 200:
                    raise UpdateError(f"GitHub returned HTTP {response.status_code}. Try again later.")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE:
                        raise UpdateError("GitHub's answer was too large.")
                return json.loads(body)
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            raise UpdateError("Could not reach GitHub. Check the server's internet connection.") from exc
        except ValueError as exc:
            raise UpdateError("GitHub returned an unreadable answer.") from exc

    async def check(self, *, manual: bool = True) -> dict:
        """Ask GitHub for the newest revision of main and whether it passed its tests."""
        async with self.lock:
            saved = _read("check.json", self.folder)
            last = _parse_time(saved.get("last_attempt"))
            if manual and last and _now() - last < MIN_MANUAL_GAP:
                raise UpdateError("Please wait a minute between update checks.")
            saved["last_attempt"] = _iso(_now())
            try:
                async with asyncio.timeout(45), self.client() as client:
                    head = await self.github(client, f"/commits/{BRANCH}")
                    sha = str(head.get("sha") or "")
                    if not SHA.fullmatch(sha):
                        raise UpdateError("GitHub returned an invalid revision.")
                    commit = head.get("commit") or {}
                    runs = (await self.github(client, f"/commits/{sha}/check-runs", {"per_page": 100})).get("check_runs") or []
                    runs = [{"name": _text(r.get("name"), 120), "status": r.get("status"), "conclusion": r.get("conclusion")}
                            for r in runs if isinstance(r, dict) and not NOT_A_TEST.search(str(r.get("name") or ""))]
                    latest = {
                        "revision": sha,
                        "date": _text((commit.get("committer") or {}).get("date"), 40),
                        "title": _text(str(commit.get("message") or "").split("\n", 1)[0], 200),
                        "tested": _tested(runs),
                        "checks": len(runs),
                        "failed_checks": [r["name"] for r in runs if r.get("conclusion") in FAILING][:10],
                    }
                    changes, ahead = [], None
                    current = installed(self.folder).get("revision")
                    if current and current != sha:
                        try:
                            compare = await self.github(client, f"/compare/{current}...{sha}", {"per_page": 100})
                            ahead = int(compare.get("ahead_by") or 0)
                            for item in reversed(compare.get("commits") or []):
                                title = str((item.get("commit") or {}).get("message") or "").split("\n", 1)[0]
                                changes.append(_text(title, 200))
                        except UpdateError:
                            ahead = None
                    elif current == sha:
                        ahead = 0
                saved.update(latest=latest, changes=changes[:50], ahead_by=ahead, checked_for=current,
                             checked_at=_iso(_now()), error=None)
            except UpdateError as exc:
                saved["error"] = str(exc)
            except (asyncio.TimeoutError, TypeError, AttributeError):
                saved["error"] = "The update check did not finish. Try again later."
            _write("check.json", saved, self.folder)
            return self.view()

    def view(self) -> dict:
        saved = _read("check.json", self.folder)
        current = installed(self.folder)
        latest = saved.get("latest") if isinstance(saved.get("latest"), dict) else None
        same_base = saved.get("checked_for") == current.get("revision")
        available = bool(latest and current and latest.get("revision") != current.get("revision"))
        return {
            "repository": REPOSITORY,
            "installed": current or None,
            "latest": latest,
            "ahead_by": saved.get("ahead_by") if same_base else None,
            "changes": (saved.get("changes") or []) if same_base else [],
            "checked_at": saved.get("checked_at"),
            "error": saved.get("error"),
            "update_available": available,
            "helper": helper(self.folder),
            "status": status(self.folder),
            "compare_url": (f"https://github.com/{REPOSITORY}/compare/{current['revision']}...{latest['revision']}"
                            if available else None),
        }

    def approve(self, target: str, user: str) -> dict:
        """Ask the server's update helper to install exactly `target`."""
        view = self.view()
        latest = view["latest"] or {}
        if not SHA.fullmatch(str(target or "")) or target != latest.get("revision"):
            raise UpdateError("That isn't the newest version. Check for updates again.")
        if latest.get("tested") != "passed":
            raise UpdateError("This version hasn't passed all of its tests, so it can't be installed with one click.")
        if not view["update_available"]:
            raise UpdateError("This server already runs that version, or its version isn't known yet.")
        if not view["helper"]["online"]:
            raise UpdateError("The update helper isn't running on the server. Set it up first.")
        if (view["status"] or {}).get("state") in {"pending", "running"}:
            raise UpdateError("An update is already in progress.")
        request = {"id": secrets.token_hex(8), "target": target, "requested_by": _text(user, 80),
                   "requested_at": _iso(_now())}
        _write("request.json", request, self.folder)
        _write("status.json", {"state": "pending", "id": request["id"], "target": target,
                               "message": "Waiting for the update helper…", "log": []}, self.folder)
        return self.view()

    def due(self, now: datetime | None = None) -> bool:
        last = _parse_time(_read("check.json", self.folder).get("last_attempt"))
        return not last or (now or _now()) - last >= CHECK_EVERY

    def newly_ready(self) -> dict | None:
        """A tested update nobody was told about yet; marks it as told."""
        view = self.view()
        latest = view["latest"] or {}
        if not view["update_available"] or latest.get("tested") != "passed":
            return None
        saved = _read("check.json", self.folder)
        if saved.get("notified") == latest["revision"]:
            return None
        saved["notified"] = latest["revision"]
        _write("check.json", saved, self.folder)
        return view


def checks_enabled() -> bool:
    return os.getenv("EXODUS_UPDATE_CHECKS", "true").strip().lower() not in {"0", "false", "no", "off"}


async def notify_admins(view: dict, admins: list[str], scheduler=None) -> None:
    latest = view.get("latest") or {}
    count = view.get("ahead_by")
    what = f"{count} change{'s' if count != 1 else ''}" if isinstance(count, int) and count > 0 else "new changes"
    body = f"A tested Exodus update is ready ({what}). Open Settings → License Tracker → Updates to install it."
    from src.notifications import dispatch_notification
    for admin in admins:
        if scheduler is not None:
            try:
                scheduler.add_notification("Exodus update ready", "completed", owner=admin, body=body)
            except Exception:
                pass
        await dispatch_notification(body, title="Exodus update ready", priority=3, tags=["arrow_up"], owner=admin)


async def daily_loop(updates: Updates, list_admins, scheduler=None, *, first_delay: float = 300, interval: float = 3600):
    """Check GitHub once a day and tell admins about tested updates."""
    await asyncio.sleep(first_delay)
    while True:
        try:
            if checks_enabled() and updates.due():
                await updates.check(manual=False)
                ready = updates.newly_ready()
                if ready:
                    await notify_admins(ready, list_admins(), scheduler)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass  # never let update checks disturb Exodus
        await asyncio.sleep(interval)
