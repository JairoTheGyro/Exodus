"""Exodus shared spaces (src/spaces.py, routes/space_routes.py, notes).

Isolation is the point: only members of a space see its notes, membership is
the only thing that grants access, and personal notes never leak. Same
transport and identity shim as tests/test_notes_fail_closed_auth.py.
"""
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import Note, Space, SpaceMember
import routes.note_routes as nr
import routes.space_routes as sr
from src import spaces

PEER = ("203.0.113.7", 54321)
USERS = {"admin": {"is_admin": True}, "mom": {}, "dad": {}, "kid": {}, "neighbor": {}}


class Identity:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            user = dict(scope.get("headers") or []).get(b"x-test-user")
            if user:
                scope.setdefault("state", {})["current_user"] = user.decode()
        await self.app(scope, receive, send)


@pytest.fixture
def factory(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'spaces.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    made = sessionmaker(bind=engine)
    monkeypatch.setattr(nr, "SessionLocal", made)
    monkeypatch.setattr(spaces, "SessionLocal", made)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.delenv("LOCALHOST_BYPASS", raising=False)
    return made


@pytest.fixture
def client(factory):
    app = FastAPI()
    app.state.auth_manager = SimpleNamespace(
        is_configured=True, users=USERS, is_admin=lambda u: bool(USERS.get(u, {}).get("is_admin")))
    app.include_router(nr.setup_note_routes())
    app.include_router(sr.setup_space_routes())
    transport = httpx.ASGITransport(app=Identity(app), client=PEER)
    return httpx.AsyncClient(transport=transport, base_url="http://spaces.test")


def as_(user):
    return {"x-test-user": user}


async def make_family(c):
    """mom manages "Family" with dad as a member; returns the space id."""
    space = (await c.post("/api/spaces", json={"name": "  Family  "}, headers=as_("mom"))).json()
    assert space["name"] == "Family" and space["role"] == "manager"
    added = await c.post(f"/api/spaces/{space['id']}/members", json={"username": "Dad"}, headers=as_("mom"))
    assert added.status_code == 200
    return space["id"]


async def note(c, user, title, **extra):
    response = await c.post("/api/notes", json={"title": title, **extra}, headers=as_(user))
    assert response.status_code == 200, response.text
    return response.json()


async def titles(c, user):
    return sorted(n["title"] for n in (await c.get("/api/notes", headers=as_(user))).json()["notes"])


async def test_members_see_and_edit_shared_notes_and_others_see_nothing(client):
    async with client as c:
        family = await make_family(c)
        groceries = await note(c, "mom", "Groceries", note_type="checklist",
                               items=[{"text": "milk", "done": False}], space_id=family)
        await note(c, "mom", "Mom private")
        await note(c, "dad", "Dad private")
        assert groceries["space_id"] == family

        assert await titles(c, "mom") == ["Groceries", "Mom private"]
        assert await titles(c, "dad") == ["Dad private", "Groceries"]
        assert await titles(c, "kid") == []
        assert await titles(c, "neighbor") == []

        # A member can read, edit, tick items, pin and archive.
        nid = groceries["id"]
        assert (await c.get(f"/api/notes/{nid}", headers=as_("dad"))).status_code == 200
        edit = await c.put(f"/api/notes/{nid}", json={"title": "Groceries!", "items": [
            {"text": "milk", "done": False}, {"text": "eggs", "done": False}]}, headers=as_("dad"))
        assert edit.status_code == 200 and edit.json()["title"] == "Groceries!"
        assert (await c.post(f"/api/notes/{nid}/items/1/toggle", headers=as_("dad"))).json()["items"][1]["done"]
        assert (await c.post(f"/api/notes/{nid}/pin", headers=as_("dad"))).status_code == 200

        # Outsiders get "not found" on every route, never a hint it exists.
        for method, path, body in [
            ("get", f"/api/notes/{nid}", None), ("put", f"/api/notes/{nid}", {"title": "x"}),
            ("delete", f"/api/notes/{nid}", None), ("post", f"/api/notes/{nid}/pin", None),
            ("post", f"/api/notes/{nid}/archive", None), ("post", f"/api/notes/{nid}/items/0/toggle", None),
        ]:
            response = await c.request(method.upper(), path, json=body, headers=as_("neighbor"))
            assert response.status_code == 404, (method, path)


async def test_only_the_owner_deletes_moves_or_adds_pictures(client, factory):
    async with client as c:
        family = await make_family(c)
        shared = await note(c, "mom", "Plans", space_id=family)
        nid = shared["id"]
        assert (await c.delete(f"/api/notes/{nid}", headers=as_("dad"))).status_code == 403
        for body in ({"space_id": ""}, {"image_url": "/api/upload/abc"}, {"ai_memory_enabled": False}):
            assert (await c.put(f"/api/notes/{nid}", json=body, headers=as_("dad"))).status_code == 403
        assert (await c.get(f"/api/notes/{nid}", headers=as_("mom"))).json()["space_id"] == family

        # The owner takes it back: members lose it at once.
        assert (await c.put(f"/api/notes/{nid}", json={"space_id": ""}, headers=as_("mom"))).json()["space_id"] is None
        assert await titles(c, "dad") == []
        assert (await c.delete(f"/api/notes/{nid}", headers=as_("mom"))).status_code == 200


async def test_notes_only_go_into_spaces_you_belong_to(client):
    async with client as c:
        family = await make_family(c)
        assert (await c.post("/api/notes", json={"title": "x", "space_id": family}, headers=as_("kid"))).status_code == 404
        own = await note(c, "kid", "Kid note")
        assert (await c.put(f"/api/notes/{own['id']}", json={"space_id": family}, headers=as_("kid"))).status_code == 404
        assert (await c.put(f"/api/notes/{own['id']}", json={"space_id": "no-such"}, headers=as_("kid"))).status_code == 404
        assert await titles(c, "mom") == []


async def test_managing_members(client):
    async with client as c:
        family = await make_family(c)
        # Members can't manage; unknown accounts are refused.
        assert (await c.post(f"/api/spaces/{family}/members", json={"username": "kid"}, headers=as_("dad"))).status_code == 403
        assert (await c.post(f"/api/spaces/{family}/members", json={"username": "ghost"}, headers=as_("mom"))).status_code == 404
        assert (await c.put(f"/api/spaces/{family}", json={"name": "Ours"}, headers=as_("dad"))).status_code == 403
        # Outsiders can't tell the space exists.
        assert (await c.post(f"/api/spaces/{family}/members", json={"username": "kid"}, headers=as_("neighbor"))).status_code == 404
        listed = (await c.get("/api/spaces", headers=as_("dad"))).json()["spaces"]
        assert [(s["name"], s["role"], s["can_manage"]) for s in listed] == [("Family", "member", False)]
        assert [m["username"] for m in listed[0]["members"]] == ["mom", "dad"]
        assert (await c.get("/api/spaces", headers=as_("neighbor"))).json()["spaces"] == []

        # Removing someone takes away access and returns their notes to them.
        dads = await note(c, "dad", "Dad shared", space_id=family)
        assert "Dad shared" in await titles(c, "mom")
        assert (await c.delete(f"/api/spaces/{family}/members/dad", headers=as_("mom"))).status_code == 200
        assert await titles(c, "mom") == []
        assert await titles(c, "dad") == ["Dad shared"]
        assert (await c.get(f"/api/notes/{dads['id']}", headers=as_("dad"))).json()["space_id"] is None


async def test_leaving_and_the_last_manager_rule(client):
    async with client as c:
        family = await make_family(c)
        assert (await c.delete(f"/api/spaces/{family}/members/mom", headers=as_("mom"))).status_code == 409
        assert (await c.delete(f"/api/spaces/{family}/members/dad", headers=as_("dad"))).status_code == 200
        assert (await c.get("/api/spaces", headers=as_("dad"))).json()["spaces"] == []
        # Promote, then the first manager may leave.
        await c.post(f"/api/spaces/{family}/members", json={"username": "kid", "role": "manager"}, headers=as_("mom"))
        assert (await c.delete(f"/api/spaces/{family}/members/mom", headers=as_("mom"))).status_code == 200
        assert [s["role"] for s in (await c.get("/api/spaces", headers=as_("kid"))).json()["spaces"]] == ["manager"]


async def test_deleting_a_space_keeps_every_note(client, factory):
    async with client as c:
        family = await make_family(c)
        await note(c, "mom", "Mom shared", space_id=family)
        await note(c, "dad", "Dad shared", space_id=family)
        assert (await c.delete(f"/api/spaces/{family}", headers=as_("dad"))).status_code == 403
        assert (await c.delete(f"/api/spaces/{family}", headers=as_("mom"))).status_code == 200
        assert await titles(c, "mom") == ["Mom shared"]
        assert await titles(c, "dad") == ["Dad shared"]
        db = factory()
        try:
            assert db.query(Space).count() == 0 and db.query(SpaceMember).count() == 0
        finally:
            db.close()


async def test_admins_can_manage_every_space(client):
    async with client as c:
        family = await make_family(c)
        listed = (await c.get("/api/spaces", headers=as_("admin"))).json()["spaces"]
        assert listed[0]["id"] == family and listed[0]["role"] is None and listed[0]["can_manage"] is True
        assert (await c.put(f"/api/spaces/{family}", json={"name": "Peraltas"}, headers=as_("admin"))).json()["name"] == "Peraltas"
        # Managing doesn't mean reading: the admin isn't a member, so no notes.
        await note(c, "mom", "Mom shared", space_id=family)
        assert await titles(c, "admin") == []


@pytest.mark.parametrize("name", ["", "   ", "x" * 41, "bad\u0007name", None])
async def test_space_names_are_checked(client, name):
    async with client as c:
        assert (await c.post("/api/spaces", json={"name": name}, headers=as_("mom"))).status_code == 400


async def test_spaces_need_accounts(client):
    async with client as c:
        assert (await c.get("/api/spaces")).status_code == 401


def test_a_rename_carries_spaces_along():
    # routes/auth_routes.py renames every mapped model with an `owner` column.
    assert hasattr(Space, "owner") and hasattr(SpaceMember, "owner")


def test_wired_into_the_app():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    app = (root / "app.py").read_text(encoding="utf-8")
    assert "from routes.space_routes import setup_space_routes" in app
    override = (root / "docker-compose.override.yml").read_text(encoding="utf-8")
    assert "./src/spaces.py:/app/src/spaces.py:ro" in override
    assert "./routes/space_routes.py:/app/routes/space_routes.py:ro" in override
    assert "_migrate_add_note_space_id()" in (root / "core" / "database.py").read_text(encoding="utf-8")


def test_existing_databases_get_the_space_column(tmp_path, monkeypatch):
    import sqlite3
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE notes (id VARCHAR PRIMARY KEY, owner VARCHAR, title VARCHAR)")
    conn.execute("INSERT INTO notes VALUES ('n1', 'mom', 'kept')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{path}")
    cdb._migrate_add_note_space_id()
    cdb._migrate_add_note_space_id()  # running twice is harmless
    conn = sqlite3.connect(path)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(notes)")]
        assert "space_id" in columns
        assert conn.execute("SELECT title, space_id FROM notes").fetchall() == [("kept", None)]
    finally:
        conn.close()


def test_spaces_ui_in_a_real_browser():
    import shutil
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    if not shutil.which("node") or not (root / "node_modules" / "playwright").exists():
        pytest.skip("node with the playwright package is required (npm ci)")
    result = subprocess.run(["node", "tests/browser/sharedSpaces.mjs"], cwd=root,
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: spaces settings card" in result.stdout


def test_spaces_ui_is_wired():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    html = (root / "static" / "index.html").read_text(encoding="utf-8")
    panel = html.split('data-settings-panel="account"', 1)[1].split('data-settings-panel=', 1)[0]
    assert 'id="spaces-card"' in panel and 'id="spaces-rows"' in panel
    settings = (root / "static" / "js" / "settings.js").read_text(encoding="utf-8")
    assert "if (tab === 'account') mountSpacesSettings(byId('spaces-rows'));" in settings
    sw = (root / "static" / "sw.js").read_text(encoding="utf-8")
    assert "'/static/js/settings/spacesSettings.js'" in sw and "'/static/js/features/notes/ui/spaces.js'" in sw
    rendering = (root / "frontend" / "src" / "features" / "notes" / "ui" / "cardRendering.js").read_text(encoding="utf-8")
    assert "${spaceBadgeHtml(note)}" in rendering
    clipboard = (root / "frontend" / "src" / "features" / "notes" / "ui" / "clipboard.js").read_text(encoding="utf-8")
    assert "addShareItems(menu, note," in clipboard
