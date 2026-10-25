# routes/move_in_routes.py
# Exodus "Move to Exodus" (src/move_in.py): upload one export, see what's in
# it, then import the chosen parts. Uploads stream to a private temporary file
# (never unpacked), are tied to the person who sent them, and are deleted
# after importing or after two hours.
import os
import secrets
import threading
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from src import move_in
from src.auth_helpers import require_user

MAX_UPLOAD_BYTES = int(os.environ.get("EXODUS_MOVE_IN_MAX_BYTES", str(2 * 1024 ** 3)))
KEEP_SECONDS = 2 * 3600
_uploads: dict[str, dict] = {}
_lock = threading.Lock()


class ImportBody(BaseModel):
    token: str
    calendars: bool = True
    contacts: bool = True
    notes: bool = True
    files: bool = True


def _folder() -> str:
    from src.constants import DATA_DIR
    path = os.path.join(DATA_DIR, "move-in")
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def _forget_old() -> None:
    now = time.time()
    with _lock:
        for token, entry in list(_uploads.items()):
            if now - entry["at"] > KEEP_SECONDS:
                _uploads.pop(token, None)
                try:
                    os.unlink(entry["path"])
                except OSError:
                    pass


def setup_move_in_routes() -> APIRouter:
    router = APIRouter(prefix="/api/move-in", tags=["move-in"])

    def _who(request: Request) -> Optional[str]:
        return require_user(request) or None

    def _is_admin(request: Request, user: Optional[str]) -> bool:
        if not user:
            return True  # single-user install: the one person is the admin
        auth = getattr(request.app.state, "auth_manager", None)
        try:
            return bool(auth and auth.is_admin(user))
        except Exception:
            return False

    def _entry(token: str, user: Optional[str]) -> dict:
        with _lock:
            entry = _uploads.get(token)
        if not entry or entry["owner"] != user:
            raise HTTPException(404, "That upload has expired. Upload the export again.")
        return entry

    @router.post("/scan")
    async def scan(request: Request):
        user = _who(request)
        _forget_old()
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "That export is too big. In Google Takeout choose 2 GB parts and import them one at a time.")
        filename = os.path.basename(request.headers.get("x-filename", "") or "export.zip")[:200]
        token = secrets.token_urlsafe(18)
        path = os.path.join(_folder(), f"{token}.upload")
        received = 0
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            with os.fdopen(fd, "wb") as out:
                async for chunk in request.stream():
                    received += len(chunk)
                    if received > MAX_UPLOAD_BYTES:
                        raise HTTPException(413, "That export is too big. In Google Takeout choose 2 GB parts and import them one at a time.")
                    out.write(chunk)
            if received == 0:
                raise HTTPException(400, "The upload was empty.")
            result = await run_in_threadpool(move_in.scan, path, filename)
        except BaseException:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
        with _lock:
            _uploads[token] = {"owner": user, "path": path, "filename": filename, "at": time.time()}
        summary = result.summary()
        summary["contacts_need_admin"] = bool(summary["contacts"]) and not _is_admin(request, user)
        return {"token": token, "filename": filename, "summary": summary}

    @router.post("/import")
    async def run(request: Request, body: ImportBody):
        user = _who(request)
        entry = _entry(body.token, user)
        choose = {"calendar": body.calendars, "contacts": body.contacts, "keep": body.notes, "file": body.files}
        try:
            report = await run_in_threadpool(move_in.run_import, entry["path"], entry["filename"], user,
                                             choose=choose, is_admin=_is_admin(request, user))
        finally:
            with _lock:
                _uploads.pop(body.token, None)
            try:
                os.unlink(entry["path"])
            except OSError:
                pass
        return report

    @router.delete("/{token}")
    def cancel(request: Request, token: str):
        user = _who(request)
        entry = _entry(token, user)
        with _lock:
            _uploads.pop(token, None)
        try:
            os.unlink(entry["path"])
        except OSError:
            pass
        return {"ok": True}

    return router
