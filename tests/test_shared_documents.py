"""Exodus shared spaces, part 3: shared documents (Library).

Members of a space can open, edit and see the history of a document shared
there, including PDF/Word-backed ones (tests/test_shared_uploads.py covers
reading the source file). Only the owner can delete, archive or re-share it,
and members can't add files or pictures.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import Document, DocumentVersion
import routes.document_routes as dr
import routes.space_routes as sr
from src import spaces

PEER = ("203.0.113.7", 54321)
USERS = {"admin": {"is_admin": True}, "mom": {}, "dad": {}, "neighbor": {}}
UPLOAD = "0123456789abcdef0123456789abcdef"


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
    engine = create_engine(f"sqlite:///{tmp_path / 'docs.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    made = sessionmaker(bind=engine)
    monkeypatch.setattr(dr, "SessionLocal", made)
    monkeypatch.setattr(spaces, "SessionLocal", made)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.delenv("LOCALHOST_BYPASS", raising=False)
    db = made()
    for doc_id, owner, content in [
        ("plan", "mom", "# Trip plan\nPack sunscreen."),
        ("mom-private", "mom", "Mom's diary"),
        ("dad-private", "dad", "Dad's list"),
        ("scan", "mom", f'<!-- pdf_source upload_id="{UPLOAD}" -->\nScanned form'),
    ]:
        db.add(Document(id=doc_id, owner=owner, title=doc_id, language="markdown",
                        current_content=content, version_count=1, is_active=True))
        db.add(DocumentVersion(id=f"{doc_id}-v1", document_id=doc_id, version_number=1,
                               content=content, summary="Created", source="user"))
    db.commit()
    db.close()
    return made


@pytest.fixture
def client(factory):
    app = FastAPI()
    app.state.auth_manager = SimpleNamespace(
        is_configured=True, users=USERS, is_admin=lambda u: bool(USERS.get(u, {}).get("is_admin")))
    app.include_router(dr.setup_document_routes(MagicMock(), None))
    app.include_router(sr.setup_space_routes())
    transport = httpx.ASGITransport(app=Identity(app), client=PEER)
    return httpx.AsyncClient(transport=transport, base_url="http://docs.test")


def as_(user):
    return {"x-test-user": user}


async def family(c):
    space = (await c.post("/api/spaces", json={"name": "Family"}, headers=as_("mom"))).json()["id"]
    await c.post(f"/api/spaces/{space}/members", json={"username": "dad"}, headers=as_("mom"))
    return space


async def library(c, user):
    response = await c.get("/api/documents/library", headers=as_(user))
    assert response.status_code == 200, response.text
    return sorted(d["id"] for d in response.json()["documents"])


async def test_members_open_edit_and_see_history(client):
    async with client as c:
        space = await family(c)
        shared = await c.put("/api/spaces/documents/plan", json={"space_id": space}, headers=as_("mom"))
        assert shared.status_code == 200 and shared.json()["space_id"] == space

        assert await library(c, "dad") == ["dad-private", "plan"]
        assert await library(c, "mom") == ["mom-private", "plan", "scan"]
        assert await library(c, "neighbor") == []

        got = await c.get("/api/document/plan", headers=as_("dad"))
        assert got.status_code == 200 and got.json()["space_id"] == space and got.json()["owner"] == "mom"
        edit = await c.put("/api/document/plan", json={"content": "# Trip plan\nPack sunscreen and hats."}, headers=as_("dad"))
        assert edit.status_code == 200, edit.text
        assert "hats" in (await c.get("/api/document/plan", headers=as_("mom"))).json()["current_content"]
        assert (await c.get("/api/document/plan/versions", headers=as_("dad"))).status_code == 200
        assert (await c.get("/api/document/plan/version/1", headers=as_("dad"))).status_code == 200
        assert (await c.post("/api/document/plan/restore/1", headers=as_("dad"))).status_code == 200


async def test_owner_only_actions_and_outsiders(client):
    async with client as c:
        space = await family(c)
        await c.put("/api/spaces/documents/plan", json={"space_id": space}, headers=as_("mom"))
        # Members can't delete, archive or re-share; outsiders can't see it at all.
        assert (await c.delete("/api/document/plan", headers=as_("dad"))).status_code == 404
        assert (await c.post("/api/document/plan/archive", headers=as_("dad"))).status_code == 404
        assert (await c.put("/api/spaces/documents/plan", json={"space_id": ""}, headers=as_("dad"))).status_code == 404
        for method, path, body in [("GET", "/api/document/plan", None), ("PUT", "/api/document/plan", {"content": "x"}),
                                   ("GET", "/api/document/plan/versions", None), ("POST", "/api/document/plan/restore/1", None)]:
            assert (await c.request(method, path, json=body, headers=as_("neighbor"))).status_code == 404, path
        # Members can't slip someone's uploaded file into the shared document.
        sneaky = await c.put("/api/document/plan", json={"content": f'<!-- pdf_source upload_id="{UPLOAD}" -->'}, headers=as_("dad"))
        assert sneaky.status_code == 403
        # The owner takes it back.
        assert (await c.put("/api/spaces/documents/plan", json={"space_id": None}, headers=as_("mom"))).status_code == 200
        assert await library(c, "dad") == ["dad-private"]


async def test_sharing_rules(client):
    async with client as c:
        space = await family(c)
        # PDF/Word-backed documents can be shared too (members read the source file).
        assert (await c.put("/api/spaces/documents/scan", json={"space_id": space}, headers=as_("mom"))).status_code == 200
        assert (await c.put("/api/spaces/documents/dad-private", json={"space_id": space}, headers=as_("mom"))).status_code == 404
        assert (await c.put("/api/spaces/documents/plan", json={"space_id": "nope"}, headers=as_("mom"))).status_code == 404
        assert (await c.put("/api/spaces/documents/plan", json={"space_id": space}, headers=as_("neighbor"))).status_code == 404


async def test_leaving_or_deleting_the_space_returns_documents(client):
    async with client as c:
        space = await family(c)
        await c.put("/api/spaces/documents/plan", json={"space_id": space}, headers=as_("mom"))
        await c.put("/api/spaces/documents/dad-private", json={"space_id": space}, headers=as_("dad"))
        assert (await c.get("/api/spaces", headers=as_("mom"))).json()["spaces"][0]["document_count"] == 2
        assert await library(c, "mom") == ["dad-private", "mom-private", "plan", "scan"]
        await c.delete(f"/api/spaces/{space}/members/dad", headers=as_("dad"))
        assert await library(c, "mom") == ["mom-private", "plan", "scan"]
        assert await library(c, "dad") == ["dad-private"]
        await c.delete(f"/api/spaces/{space}", headers=as_("mom"))
        assert (await c.get("/api/document/plan", headers=as_("mom"))).json()["space_id"] is None


def test_existing_databases_get_the_document_space_column(tmp_path, monkeypatch):
    import sqlite3
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE documents (id VARCHAR PRIMARY KEY, owner VARCHAR, title VARCHAR)")
    conn.execute("INSERT INTO documents VALUES ('d1', 'mom', 'Kept')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{path}")
    cdb._migrate_add_document_space_id()
    cdb._migrate_add_document_space_id()
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT title, space_id FROM documents").fetchall() == [("Kept", None)]
    finally:
        conn.close()
