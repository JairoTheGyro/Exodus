"""Exodus service manager helper ("servicectl").

The only part of Exodus that talks to Docker. It accepts a fixed set of
actions on a fixed list of optional services and nothing else:

    GET  /services                         status of every managed service
    POST /services/<name>/start            turn on (recreate if removed)
    POST /services/<name>/stop             turn off (container kept)
    POST /services/<name>/remove           delete container + image; data kept,
                                           or {"delete_data": true} also deletes
                                           its Docker volumes (never host folders)
    POST /services/<name>/reinstall        download/build again, then turn on

The Exodus app itself, and this helper, are never managed. Requests need the
bearer token this helper writes to TOKEN_PATH (shared read-only with the app).
It listens only on the internal Docker network; no port is published.

The chosen state ("on", "off", "removed") is remembered in STATE_PATH, and a
background loop keeps services that were turned off from being started again
by `docker compose up` (the app container depends on some of them).

Every Docker call is an argv list (no shell) built from the allow-list below.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROJECT = os.environ.get("EXODUS_COMPOSE_PROJECT", "sovereign-hub")
PROJECT_DIR = os.environ.get("EXODUS_PROJECT_DIR", "")
TOKEN_PATH = os.environ.get("SERVICECTL_TOKEN_PATH", "/run/servicectl/token")
STATE_PATH = os.environ.get("SERVICECTL_STATE_PATH", "/state/desired.json")
PORT = int(os.environ.get("SERVICECTL_PORT", "8095"))
RECONCILE_SECONDS = 30

# name -> (label, Docker named volumes holding its data, host folders holding
# its data (reported only, never deleted), compose profile or None)
SERVICES = {
    "searxng": ("SearXNG", ["searxng-data"], [], None),
    "chromadb": ("ChromaDB", ["chromadb-data"], [], None),
    "ntfy": ("ntfy", ["ntfy-cache"], [], None),
    "vaultwarden": ("Vaultwarden", ["vaultwarden-secrets"], ["data/vaultwarden"], None),
    "harness": ("Code (DeepSeek Harness)", ["harness-home"], ["data/code-projects"], None),
    "replica": ("Replica video player", [], ["data/replica"], "replica"),
}
ACTIONS = ("start", "stop", "remove", "reinstall")
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,40}$")

_lock = threading.Lock()
_busy: dict[str, str] = {}
_last_error: dict[str, str] = {}


def run(argv, timeout=900):
    """Run a fixed docker argv; never through a shell."""
    assert isinstance(argv, list) and argv and argv[0] == "docker"
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def compose(*args):
    argv = ["docker", "compose", "-p", PROJECT]
    if PROJECT_DIR:
        argv += ["--project-directory", PROJECT_DIR]
    return argv + list(args)


# ── state ─────────────────────────────────────────────────────────────

def load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
        return {k: v for k, v in data.items() if k in SERVICES and v in ("on", "off", "removed")}
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(state, handle)
    os.replace(tmp, STATE_PATH)


def set_desired(name: str, value: str) -> None:
    with _lock:
        state = load_state()
        state[name] = value
        save_state(state)


# ── docker queries ────────────────────────────────────────────────────

def container(name: str):
    """(id, running, image) of the service's container, or None."""
    code, out, _ = run([
        "docker", "ps", "-a",
        "--filter", f"label=com.docker.compose.project={PROJECT}",
        "--filter", f"label=com.docker.compose.service={name}",
        "--format", "{{.ID}}\t{{.State}}\t{{.Image}}",
    ], timeout=30)
    if code != 0 or not out:
        return None
    cid, state, image = (out.splitlines()[0].split("\t") + ["", "", ""])[:3]
    return cid, state == "running", image


def status(name: str) -> dict:
    label, volumes, folders, profile = SERVICES[name]
    found = container(name)
    if found is None:
        state = "removed"
    else:
        state = "running" if found[1] else "stopped"
    return {
        "name": name, "label": label, "state": state, "desired": load_state().get(name),
        "busy": _busy.get(name), "error": _last_error.get(name),
        "data_volumes": volumes, "data_folders": folders, "optional_profile": profile,
    }


# ── actions ───────────────────────────────────────────────────────────

def _check(result, what):
    code, _, err = result
    if code != 0:
        raise RuntimeError(f"{what} failed: {err[-400:] or 'unknown error'}")


def _profile_args(name):
    profile = SERVICES[name][3]
    return ["--profile", profile] if profile else []


def do_start(name):
    found = container(name)
    if found:
        _check(run(["docker", "start", found[0]], timeout=120), "start")
    else:
        _check(run(compose(*_profile_args(name), "up", "-d", "--no-deps", name)), "create")
    set_desired(name, "on")


def do_stop(name):
    set_desired(name, "off")
    found = container(name)
    if found and found[1]:
        _check(run(["docker", "stop", found[0]], timeout=120), "stop")


def do_remove(name, delete_data=False):
    set_desired(name, "removed")
    found = container(name)
    if found:
        _check(run(["docker", "rm", "-f", found[0]], timeout=120), "remove")
        # The image is only deleted when nothing else uses it.
        run(["docker", "image", "rm", found[2]], timeout=120)
    if delete_data:
        for volume in SERVICES[name][1]:
            run(["docker", "volume", "rm", f"{PROJECT}_{volume}"], timeout=120)


def do_reinstall(name):
    args = _profile_args(name)
    if any(name == n for n in ("harness", "replica")):
        _check(run(compose(*args, "build", name), timeout=3600), "build")
    else:
        _check(run(compose(*args, "pull", name), timeout=3600), "download")
    _check(run(compose(*args, "up", "-d", "--no-deps", "--force-recreate", name)), "start")
    set_desired(name, "on")


def perform(name, action, delete_data=False):
    """Run an action in the background; returns False if one is running."""
    if name not in SERVICES or action not in ACTIONS:
        raise ValueError("unknown service or action")
    with _lock:
        if _busy.get(name):
            return False
        _busy[name] = action
        _last_error.pop(name, None)

    def work():
        try:
            if action == "start":
                do_start(name)
            elif action == "stop":
                do_stop(name)
            elif action == "remove":
                do_remove(name, delete_data=delete_data)
            else:
                do_reinstall(name)
        except Exception as error:  # reported through /services
            _last_error[name] = str(error)[:500]
        finally:
            _busy.pop(name, None)

    threading.Thread(target=work, daemon=True).start()
    return True


def reconcile_once():
    """Keep services that were turned off (or removed) from running again."""
    for name, desired in load_state().items():
        if _busy.get(name) or desired == "on":
            continue
        found = container(name)
        if found and found[1]:
            if desired == "off":
                run(["docker", "stop", found[0]], timeout=120)
            else:
                run(["docker", "rm", "-f", found[0]], timeout=120)


def reconcile_forever():
    while True:
        try:
            reconcile_once()
        except Exception:
            pass
        time.sleep(RECONCILE_SECONDS)


# ── HTTP ──────────────────────────────────────────────────────────────

def load_or_create_token(path=None):
    path = path or TOKEN_PATH
    try:
        with open(path, encoding="utf-8") as handle:
            token = handle.read().strip()
        if len(token) >= 32:
            return token
    except OSError:
        pass
    token = secrets.token_urlsafe(32)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    with os.fdopen(fd, "w") as handle:
        handle.write(token)
    return token


class Handler(BaseHTTPRequestHandler):
    token = ""

    def log_message(self, *args):  # quiet
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self):
        header = self.headers.get("Authorization", "")
        given = header[7:] if header.startswith("Bearer ") else ""
        return bool(self.token) and hmac.compare_digest(given.encode(), self.token.encode())

    def do_GET(self):
        if not self._authorized():
            return self._send(401, {"detail": "unauthorized"})
        if self.path.rstrip("/") != "/services":
            return self._send(404, {"detail": "not found"})
        self._send(200, {"services": [status(name) for name in SERVICES]})

    def do_POST(self):
        if not self._authorized():
            return self._send(401, {"detail": "unauthorized"})
        parts = self.path.strip("/").split("/")
        if len(parts) != 3 or parts[0] != "services" or not NAME_RE.match(parts[1]):
            return self._send(404, {"detail": "not found"})
        name, action = parts[1], parts[2]
        if name not in SERVICES or action not in ACTIONS:
            return self._send(404, {"detail": "unknown service or action"})
        delete_data = False
        length = min(int(self.headers.get("Content-Length") or 0), 1024)
        if length:
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                delete_data = action == "remove" and body.get("delete_data") is True
            except ValueError:
                return self._send(400, {"detail": "bad JSON"})
        if not perform(name, action, delete_data=delete_data):
            return self._send(409, {"detail": "busy"})
        self._send(202, {"accepted": action, "service": name})


def main():
    Handler.token = load_or_create_token()
    threading.Thread(target=reconcile_forever, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
