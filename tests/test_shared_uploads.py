"""Exodus shared spaces: members can READ files behind shared notes and documents.

A member may open an uploaded file (a picture, or a PDF/Word source) only when
a note or document shared in one of their spaces points at it AND the file
belongs to that item's owner. They can never change it, API tokens never get
this, and everyone else still gets "not found".
"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import Document, Note
from src import spaces
from test_upload_routes_owner_scope import _AuthManager, _Request, _add_upload_row, _make_upload_store, _upload_endpoints

USERS = {"alice": {}, "bob": {}, "carol": {}}
CAROL_FILE = "c" * 32 + ".png"


@pytest.fixture
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'up.db'}", connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    made = sessionmaker(bind=engine)
    monkeypatch.setattr(spaces, "SessionLocal", made)
    handler, alice_file, bob_file, upload_dir = _make_upload_store(tmp_path, monkeypatch)
    carol_path = upload_dir / "2026" / "06" / "02" / CAROL_FILE
    carol_path.write_bytes(b"carol image bytes")
    _add_upload_row(upload_dir, {"id": CAROL_FILE, "path": str(carol_path), "mime": "image/png",
                                 "size": carol_path.stat().st_size, "name": "carol.png", "owner": "carol"})
    space = spaces.create_space("alice", "Family")["id"]
    spaces.add_member("alice", space, "bob", USERS)
    db = made()
    # alice shares a note with her picture, plus (sneakily) carol's file id.
    db.add(Note(id="n1", owner="alice", title="Trip", space_id=space,
                content=f"![photo](/api/upload/{alice_file}) and /api/upload/{CAROL_FILE}"))
    # alice's PDF document, shared too.
    db.add(Document(id="d1", owner="alice", title="Form", language="markdown", version_count=1, is_active=True,
                    space_id=space, current_content=f'<!-- pdf_source upload_id="{alice_file}" -->\nName: '))
    db.commit()
    db.close()
    return SimpleNamespace(made=made, space=space, handler=handler, alice_file=alice_file, bob_file=bob_file)


def test_only_members_get_the_owner_of_a_referenced_file(world):
    assert spaces.shared_upload_owner("bob", world.alice_file) == "alice"
    assert spaces.shared_upload_owner("carol", world.alice_file) is None  # not a member
    assert spaces.shared_upload_owner("alice", world.alice_file) is None  # the owner uses her own access
    assert spaces.shared_upload_owner("bob", "f" * 32 + ".png") is None  # not referenced anywhere
    assert spaces.shared_upload_owner(None, world.alice_file) is None


def test_a_bare_id_in_text_is_not_a_reference(world):
    db = world.made()
    db.add(Note(id="n2", owner="alice", title="x", space_id=world.space, content=f"checksum {world.bob_file}"))
    db.commit()
    db.close()
    assert spaces.shared_upload_owner("bob", world.bob_file) is None


def test_unsharing_takes_access_away(world):
    db = world.made()
    db.query(Note).update({Note.space_id: None})
    db.query(Document).update({Document.space_id: None})
    db.commit()
    db.close()
    assert spaces.shared_upload_owner("bob", world.alice_file) is None


def download(world, monkeypatch, user, file_id, token=False):
    download_file = _upload_endpoints(world.handler, monkeypatch)["download_file"]
    request = _Request(user=user, auth_manager=_AuthManager())
    if token:
        request.state.api_token = True
        request.state.api_token_owner = user
        request.state.api_token_scopes = ["uploads:read"]
    return asyncio.run(download_file(request, file_id))


def test_members_can_download_the_shared_picture(world, monkeypatch):
    response = download(world, monkeypatch, "bob", world.alice_file)
    assert response.status_code == 200 and response.path.endswith(world.alice_file)


@pytest.mark.parametrize("user,file_attr,token", [
    ("carol", "alice_file", False),   # outsider
    ("bob", "alice_file", True),      # API token, even the member's own
])
def test_others_still_get_not_found(world, monkeypatch, user, file_attr, token):
    with pytest.raises(HTTPException) as caught:
        download(world, monkeypatch, user, getattr(world, file_attr), token=token)
    assert caught.value.status_code in (403, 404)


def test_a_shared_note_cannot_leak_a_third_persons_file(world, monkeypatch):
    # alice's shared note mentions carol's file, but it isn't alice's to share.
    with pytest.raises(HTTPException) as caught:
        download(world, monkeypatch, "bob", CAROL_FILE)
    assert caught.value.status_code == 404


@pytest.fixture
def documents(world, monkeypatch):
    import routes.document_routes as dr
    monkeypatch.setattr(dr, "SessionLocal", world.made)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.delenv("LOCALHOST_BYPASS", raising=False)

    def no_viewer():
        raise RuntimeError("PDF viewer not installed in this test")

    monkeypatch.setattr("src.pdf_runtime.load_pymupdf_for_pdf_viewer", no_viewer)
    app = FastAPI()
    app.state.auth_manager = SimpleNamespace(is_configured=True, users=USERS, is_admin=lambda u: False)
    app.include_router(dr.setup_document_routes(MagicMock(), world.handler))

    class Identity:
        def __init__(self, inner):
            self.inner = inner

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                user = dict(scope.get("headers") or []).get(b"x-test-user")
                if user:
                    scope.setdefault("state", {})["current_user"] = user.decode()
            await self.inner(scope, receive, send)

    transport = httpx.ASGITransport(app=Identity(app), client=("203.0.113.7", 5000))
    return httpx.AsyncClient(transport=transport, base_url="http://docs.test")


async def test_members_can_open_a_shared_pdf_document(documents):
    async with documents as c:
        # 503 = the source PDF was found and only the (absent) viewer is missing;
        # 404 = the file or document wasn't reachable.
        member = await c.get("/api/document/d1/render-pages", headers={"x-test-user": "bob"})
        assert member.status_code == 503, member.text
        outsider = await c.get("/api/document/d1/render-pages", headers={"x-test-user": "carol"})
        assert outsider.status_code == 404
        # Writing routes stay with the owner.
        assert (await c.post("/api/document/d1/extract-pdf-text", headers={"x-test-user": "bob"})).status_code == 404


async def test_members_edit_text_but_cannot_add_files(documents, world):
    async with documents as c:
        doc = (await c.get("/api/document/d1", headers={"x-test-user": "bob"})).json()
        kept = await c.put("/api/document/d1", json={"content": doc["current_content"] + "Bob"}, headers={"x-test-user": "bob"})
        assert kept.status_code == 200, kept.text  # the owner's PDF marker may stay
        added = await c.put("/api/document/d1", json={"content": doc["current_content"] + f" /api/upload/{world.bob_file}"},
                            headers={"x-test-user": "bob"})
        assert added.status_code == 403
