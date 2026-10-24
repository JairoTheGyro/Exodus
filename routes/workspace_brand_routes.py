# routes/workspace_brand_routes.py
# Exodus: the workspace's own name and logo, set by an admin and shown
# everywhere the product name and logo appear (sidebar, welcome, sign-in page,
# tab titles, tab icon, installed-app name).
#
# Reading is public (no sign-in) because the sign-in page shows the name and
# logo before anyone is signed in. Changing is admin-only. Uploaded logos are
# decoded and re-encoded as a plain PNG, so nothing but pixels is ever stored or
# served; SVG is not accepted.
import io
import json
import logging
import os
import re
import tempfile
import time
import unicodedata

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from core.middleware import require_admin
from src.constants import DATA_DIR

logger = logging.getLogger(__name__)

DEFAULT_NAME = "Exodus"
MAX_NAME_LENGTH = 40
MAX_LOGO_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_LOGO_SOURCE_PIXELS = 4096 * 4096
LOGO_SIZE = 512
ACCEPTED_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}


def brand_dir() -> str:
    return os.path.join(DATA_DIR, "workspace_brand")


def _config_path() -> str:
    return os.path.join(brand_dir(), "brand.json")


def logo_path() -> str:
    return os.path.join(brand_dir(), "logo.png")


def _atomic_write(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_brand() -> dict:
    """Saved brand settings; missing or unreadable means the defaults."""
    try:
        with open(_config_path(), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        data = {}
    name = data.get("name") if isinstance(data.get("name"), str) else ""
    version = data.get("version") if isinstance(data.get("version"), int) else 0
    return {"name": name, "version": version}


def _save_brand(name: str) -> dict:
    data = {"name": name, "version": int(time.time() * 1000)}
    _atomic_write(_config_path(), json.dumps(data).encode("utf-8"))
    return data


def clean_name(value) -> str:
    """Normalise a workspace name; '' means "use the default"."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise HTTPException(400, "Workspace name must be text")
    # Ordinary whitespace (tabs, newlines) becomes single spaces; anything
    # else invisible or controlling is refused.
    name = re.sub(r"\s+", " ", unicodedata.normalize("NFC", value)).strip()
    if any(unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp") for ch in name):
        raise HTTPException(400, "Workspace name can't contain control characters")
    if len(name) > MAX_NAME_LENGTH:
        raise HTTPException(400, f"Workspace name can be at most {MAX_NAME_LENGTH} characters")
    return name


def normalise_logo(raw: bytes) -> bytes:
    """Decode an uploaded image and return a square-fitting PNG of its pixels."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    if len(raw) > MAX_LOGO_UPLOAD_BYTES:
        raise HTTPException(413, "Logo must be 2 MB or smaller")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            fmt = probe.format
            width, height = probe.size
            probe.verify()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise HTTPException(400, "Logo must be a PNG, JPEG, WebP or GIF image")
    if fmt not in ACCEPTED_FORMATS:
        raise HTTPException(400, "Logo must be a PNG, JPEG, WebP or GIF image")
    if width < 16 or height < 16 or width * height > MAX_LOGO_SOURCE_PIXELS:
        raise HTTPException(400, "Logo must be between 16×16 and 4096×4096 pixels")
    with Image.open(io.BytesIO(raw)) as image:
        image.seek(0)
        image = ImageOps.exif_transpose(image).convert("RGBA")
        image.thumbnail((LOGO_SIZE, LOGO_SIZE), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def brand_payload() -> dict:
    saved = load_brand()
    has_logo = os.path.isfile(logo_path())
    version = saved["version"]
    return {
        "name": saved["name"] or DEFAULT_NAME,
        "custom_name": bool(saved["name"]),
        "default_name": DEFAULT_NAME,
        "has_logo": has_logo,
        "logo_url": f"/api/workspace/brand/logo?v={version}" if has_logo else None,
        "version": version,
        "max_name_length": MAX_NAME_LENGTH,
    }


def setup_workspace_brand_routes() -> APIRouter:
    router = APIRouter(tags=["workspace-brand"])

    @router.get("/api/workspace/brand")
    async def get_brand():
        return JSONResponse(brand_payload(), headers={"Cache-Control": "no-store"})

    @router.get("/api/workspace/brand/logo")
    async def get_logo():
        path = logo_path()
        if not os.path.isfile(path):
            raise HTTPException(404, "No workspace logo")
        return FileResponse(path, media_type="image/png", headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        })

    @router.put("/api/workspace/brand")
    async def set_name(request: Request):
        require_admin(request)
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(400, "Expected JSON")
        if not isinstance(body, dict):
            raise HTTPException(400, "Expected a JSON object")
        _save_brand(clean_name(body.get("name")))
        return brand_payload()

    @router.post("/api/workspace/brand/logo")
    async def set_logo(request: Request, file: UploadFile = File(...)):
        require_admin(request)
        raw = await file.read(MAX_LOGO_UPLOAD_BYTES + 1)
        png = normalise_logo(raw)
        _atomic_write(logo_path(), png)
        _save_brand(load_brand()["name"])  # new version → new logo URL
        return brand_payload()

    @router.delete("/api/workspace/brand/logo")
    async def remove_logo(request: Request):
        require_admin(request)
        try:
            os.unlink(logo_path())
        except FileNotFoundError:
            pass
        _save_brand(load_brand()["name"])
        return brand_payload()

    return router
