"""Read-only upstream inspection. Never pulls, installs, or changes the baseline.

Only repositories in the shipped manifest can be queried. Cache contains public
GitHub metadata, not user code or credentials. One worker, like the local app.
"""
import asyncio
import base64
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx

from core.atomic_io import atomic_write_json
from src.constants import DATA_DIR

MANIFEST = Path(__file__).resolve().parent.parent / "config/upstream_projects.json"
MAX_RESPONSE = 8_000_000


class UpdateError(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def text(value, limit=12000):
    return str(value or "")[:limit]


def commit_record(item):
    sha = item.get("sha", "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise UpdateError("GitHub returned an invalid revision.")
    commit = item.get("commit") or {}
    return {"sha": sha, "message": text(commit.get("message")),
            "date": (commit.get("committer") or {}).get("date")}


class UpdateTracker:
    def __init__(self, cache_dir=None, projects=None, transport=None):
        entries = projects if projects is not None else json.loads(MANIFEST.read_text())
        self.projects = {p["id"]: p for p in entries}
        for p in entries:
            if not re.fullmatch(r"[\w.-]+/[\w.-]+", p["repository"]):
                raise ValueError("Invalid tracked repository")
            if not re.fullmatch(r"[0-9a-f]{40}", p["used_commit"]):
                raise ValueError("An exact upstream baseline is required")
        self.cache_dir = Path(cache_dir or Path(DATA_DIR) / "upstream_updates")
        self.transport = transport
        self.lock = asyncio.Lock()

    def project(self, project_id):
        if project_id not in self.projects:
            raise KeyError(project_id)
        return self.projects[project_id]

    def path(self, project_id):
        self.project(project_id)
        # IDs come from trusted manifest, not request paths.
        if not re.fullmatch(r"[a-z0-9_-]+", project_id):
            raise ValueError("Invalid project identifier")
        return self.cache_dir / (project_id + ".json")

    def read(self, project_id):
        path = self.path(project_id)
        try:
            if path.stat().st_size > 16_000_000:
                raise ValueError("Cache too large")
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                raise ValueError("Invalid cache")
            # A source upgrade must not compare against the previous baseline.
            if data.get("baseline") != self.project(project_id)["used_commit"]:
                return {}
            if data.get("repository") != self.project(project_id)["repository"] or data.get("branch") != self.project(project_id)["branch"]:
                return {}
            return data
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            return {"error": "Saved update history could not be read. Check again to rebuild it."}

    def save(self, project_id, cache):
        cache["baseline"] = self.project(project_id)["used_commit"]
        cache["repository"] = self.project(project_id)["repository"]
        cache["branch"] = self.project(project_id)["branch"]
        try:
            atomic_write_json(str(self.path(project_id)), cache)
        except OSError as exc:
            raise UpdateError("Update history could not be saved on this server.") from exc

    def view(self, project_id):
        cache = self.read(project_id)
        return {"project": self.project(project_id), "snapshot": cache.get("snapshot"),
                "last_attempt": cache.get("last_attempt"), "error": cache.get("error")}

    async def github(self, client, repository, suffix="", params=None):
        # Do not follow response links or redirects to arbitrary destinations.
        url = f"https://api.github.com/repos/{repository}{suffix}"
        try:
            async with client.stream("GET", url, params=params) as response:
                if response.status_code in (403, 429):
                    raise UpdateError("GitHub limited or refused this request. Saved history is still available; try again later.")
                if response.status_code == 404:
                    raise UpdateError("GitHub could not find this repository, branch, or revision.")
                if response.status_code != 200:
                    raise UpdateError(f"GitHub returned HTTP {response.status_code}. Try again later.")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE:
                        raise UpdateError("This change is too large to load here. View it on GitHub.")
                return json.loads(body), 'rel="next"' in response.headers.get("link", "")
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            raise UpdateError("Could not reach GitHub. Check the server's internet connection; saved history is still available.") from exc
        except (ValueError, TypeError) as exc:
            raise UpdateError("GitHub returned an unreadable response. Saved history is still available.") from exc

    def client(self):
        return httpx.AsyncClient(timeout=15, follow_redirects=False, transport=self.transport,
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "Exodus-Update-Tracker",
                                          "X-GitHub-Api-Version": "2022-11-28"})

    async def check(self, project_id):
        project = self.project(project_id)
        async with self.lock:
            cache = self.read(project_id)
            if cache.get("last_attempt"):
                elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(cache["last_attempt"])).total_seconds()
                if elapsed < 60:
                    raise UpdateError("Please wait one minute between update checks. The last result is shown below.")
            cache["last_attempt"] = now()
            try:
                async with asyncio.timeout(50), self.client() as client:
                    repo = project["repository"]
                    commits, more = await self.github(client, repo, "/commits", {"sha": project["branch"], "per_page": 30})
                    records = [commit_record(item) for item in commits]
                    if not records:
                        raise UpdateError("This branch has no revisions to compare.")
                    head = records[0]["sha"]
                    releases, more_releases = await self.github(client, repo, "/releases", {"per_page": 10})
                    release_records = [{"tag": text(r.get("tag_name"), 200), "name": text(r.get("name"), 300),
                                        "notes": text(r.get("body"), 20000), "notes_truncated": len(r.get("body") or "") > 20000,
                                        "date": r.get("published_at"),
                                        "prerelease": bool(r.get("prerelease"))} for r in releases if not r.get("draft")]
                    comparison = None
                    comparison_error = None
                    try:
                        result, _ = await self.github(client, repo, f"/compare/{project['used_commit']}...{head}", {"per_page": 1})
                        comparison = {k: result.get(k) for k in ("status", "ahead_by", "behind_by", "total_commits")}
                    except UpdateError as exc:
                        comparison_error = str(exc)
                    latest_version = None
                    if project.get("version_file"):
                        try:
                            contents, _ = await self.github(client, repo, "/contents/" + quote(project["version_file"], safe="/"), {"ref": head})
                            source = base64.b64decode(contents.get("content", "")).decode("utf-8")
                            match = re.search(r'^APP_VERSION\s*=\s*[\'"]([^\'"\n]{1,100})[\'"]', source, re.MULTILINE)
                            latest_version = match.group(1) if match else None
                        except (UpdateError, ValueError, UnicodeError):
                            pass  # A missing version label must not hide commit history.
                    snapshot = {"checked_at": now(), "head": head, "commits": records,
                                "version": latest_version,
                                "more_commits": more, "releases": release_records, "more_releases": more_releases,
                                "comparison": comparison, "comparison_error": comparison_error}
                    # Preserve details of immutable revisions across refreshes.
                    cache.update(snapshot=snapshot, pages={}, error=None)
            except (UpdateError, asyncio.TimeoutError, TypeError, AttributeError) as exc:
                cache["error"] = str(exc) if isinstance(exc, UpdateError) else "The check did not complete. Saved history is still available."
            self.save(project_id, cache)
            return self.view(project_id)

    async def history(self, project_id, page, online=False):
        project = self.project(project_id)
        async with self.lock:
            cache = self.read(project_id)
            snapshot = cache.get("snapshot")
            if not snapshot:
                raise UpdateError("Check for updates before loading history.")
            if page == 1:
                return {"commits": snapshot["commits"], "more": snapshot["more_commits"]}
            pages = cache.setdefault("pages", {})
            if str(page) in pages:
                return pages[str(page)]
            if not online:
                raise UpdateError("This older page is not saved offline. Use Load older from GitHub when connected.")
            async with self.client() as client:
                items, more = await self.github(client, project["repository"], "/commits",
                                                {"sha": snapshot["head"], "per_page": 30, "page": page})
            result = {"commits": [commit_record(item) for item in items], "more": more}
            pages[str(page)] = result
            while len(pages) > 30:
                del pages[next(iter(pages))]
            self.save(project_id, cache)
            return result

    async def detail(self, project_id, sha, online=False):
        project = self.project(project_id)
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise UpdateError("Invalid revision identifier.")
        async with self.lock:
            cache = self.read(project_id)
            details = cache.setdefault("details", {})
            if sha in details:
                return details[sha]
            if not online:
                raise UpdateError("File changes for this revision are not saved. Use Load file changes from GitHub when connected.")
            async with self.client() as client:
                item, more = await self.github(client, project["repository"], f"/commits/{sha}", {"per_page": 100})
            result = commit_record(item)
            result.update(files=[{"name": text(f.get("filename"), 1000), "previous_name": text(f.get("previous_filename"), 1000),
                                  "status": text(f.get("status"), 30), "additions": f.get("additions", 0),
                                  "deletions": f.get("deletions", 0)} for f in item.get("files", [])],
                          stats=item.get("stats", {}), more_files=more)
            details[sha] = result
            while len(details) > 40:
                del details[next(iter(details))]
            self.save(project_id, cache)
            return result
