"""Exodus workspace name and logo (routes/workspace_brand_routes.py)."""
import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

import routes.workspace_brand_routes as brand

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(brand, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr("core.middleware.auth_disabled", lambda: False)
    app = FastAPI()
    app.state.auth_manager = SimpleNamespace(is_configured=True, is_admin=lambda user: user == "admin")

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.current_user = request.headers.get("x-test-user")
        return await call_next(request)

    app.include_router(brand.setup_workspace_brand_routes())
    return TestClient(app)


ADMIN = {"x-test-user": "admin"}
MEMBER = {"x-test-user": "alice"}


def image_bytes(fmt="PNG", size=(64, 48), color=(200, 30, 30, 255)):
    out = io.BytesIO()
    mode = "RGBA" if fmt in ("PNG", "WEBP", "GIF") else "RGB"
    Image.new(mode, size, color[: len(mode)]).save(out, format=fmt)
    return out.getvalue()


def test_defaults_are_public_and_say_exodus(client):
    data = client.get("/api/workspace/brand").json()
    assert data["name"] == "Exodus" and data["custom_name"] is False
    assert data["has_logo"] is False and data["logo_url"] is None
    assert client.get("/api/workspace/brand/logo").status_code == 404


def test_admin_sets_a_clean_name_and_everyone_reads_it(client):
    response = client.put("/api/workspace/brand", json={"name": "  Peralta   Family\tHub "}, headers=ADMIN)
    assert response.status_code == 200
    assert response.json()["name"] == "Peralta Family Hub"
    data = client.get("/api/workspace/brand").json()
    assert data["name"] == "Peralta Family Hub" and data["custom_name"] is True


@pytest.mark.parametrize("name,status", [
    ("x" * 41, 400),
    ("Bad\u0007name", 400),
    ("Hidden​join", 400),
    (12, 400),
])
def test_bad_names_are_refused(client, name, status):
    assert client.put("/api/workspace/brand", json={"name": name}, headers=ADMIN).status_code == status
    assert client.get("/api/workspace/brand").json()["name"] == "Exodus"


def test_empty_name_goes_back_to_the_default(client):
    client.put("/api/workspace/brand", json={"name": "Acme"}, headers=ADMIN)
    data = client.put("/api/workspace/brand", json={"name": "   "}, headers=ADMIN).json()
    assert data["name"] == "Exodus" and data["custom_name"] is False


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP", "GIF"])
def test_logo_upload_is_reencoded_as_a_bounded_png(client, fmt):
    raw = image_bytes(fmt, size=(1200, 800))
    response = client.post("/api/workspace/brand/logo", files={"file": (f"logo.{fmt.lower()}", raw)}, headers=ADMIN)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["has_logo"] is True and data["logo_url"].startswith("/api/workspace/brand/logo?v=")
    served = client.get(data["logo_url"])
    assert served.status_code == 200 and served.headers["content-type"] == "image/png"
    assert served.headers["x-content-type-options"] == "nosniff"
    with Image.open(io.BytesIO(served.content)) as image:
        assert image.format == "PNG" and max(image.size) == 512


def test_svg_and_non_images_are_refused(client):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    for payload in (svg, b"not an image at all", image_bytes("BMP", size=(64, 64))):
        response = client.post("/api/workspace/brand/logo", files={"file": ("logo", payload)}, headers=ADMIN)
        assert response.status_code == 400
    assert client.get("/api/workspace/brand").json()["has_logo"] is False


def test_logo_size_limits(client):
    tiny = image_bytes("PNG", size=(8, 8))
    assert client.post("/api/workspace/brand/logo", files={"file": ("t.png", tiny)}, headers=ADMIN).status_code == 400
    huge = b"\x89PNG" + b"0" * (brand.MAX_LOGO_UPLOAD_BYTES + 10)
    assert client.post("/api/workspace/brand/logo", files={"file": ("h.png", huge)}, headers=ADMIN).status_code == 413


def test_removing_the_logo_and_new_versions(client):
    first = client.post("/api/workspace/brand/logo", files={"file": ("a.png", image_bytes())}, headers=ADMIN).json()
    client.put("/api/workspace/brand", json={"name": "Acme"}, headers=ADMIN)
    assert client.get("/api/workspace/brand").json()["version"] != first["version"]
    data = client.delete("/api/workspace/brand/logo", headers=ADMIN).json()
    assert data["has_logo"] is False and data["name"] == "Acme"
    assert client.get("/api/workspace/brand/logo").status_code == 404


def test_only_admins_can_change_it(client):
    assert client.put("/api/workspace/brand", json={"name": "Mine"}, headers=MEMBER).status_code == 403
    assert client.put("/api/workspace/brand", json={"name": "Mine"}).status_code == 403
    assert client.post("/api/workspace/brand/logo", files={"file": ("a.png", image_bytes())}, headers=MEMBER).status_code == 403
    assert client.delete("/api/workspace/brand/logo", headers=MEMBER).status_code == 403
    assert client.get("/api/workspace/brand").json()["name"] == "Exodus"


def test_reads_are_reachable_before_sign_in_and_routes_are_registered():
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    exempt = app_source.split("AUTH_EXEMPT_EXACT = {", 1)[1].split("}", 1)[0]
    assert '"/api/workspace/brand",' in exempt and '"/api/workspace/brand/logo",' in exempt
    assert "app.include_router(setup_workspace_brand_routes())" in app_source
    override = (ROOT / "docker-compose.override.yml").read_text(encoding="utf-8")
    assert "./routes/workspace_brand_routes.py:/app/routes/workspace_brand_routes.py:ro" in override
    assert "./static/js/workspaceBrand.js:/app/static/js/workspaceBrand.js:ro" in override


@pytest.mark.skipif(not (ROOT / "node_modules" / "playwright").exists(), reason="node with the playwright package is required (npm ci)")
def test_name_and_logo_on_the_page_in_a_real_browser():
    import subprocess
    result = subprocess.run(["node", "tests/browser/workspaceBrand.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: workspace brand" in result.stdout
