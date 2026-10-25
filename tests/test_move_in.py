"""Exodus "Move to Exodus" (src/move_in.py, routes/move_in_routes.py).

A realistic fake Google Takeout ZIP is scanned and imported into a temporary
database and Library folder. Nothing touches a real account or the network.
"""
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import CalendarCal, CalendarEvent, DocumentFile, Note
import routes.move_in_routes as routes_mod
from src import move_in

ROOT = Path(__file__).resolve().parents[1]
ICS = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:a1\r\nSUMMARY:Dentist\r\n"
       b"DTSTART:20261110T150000Z\r\nDTEND:20261110T160000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
VCF = b"BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Abuela Rosa\r\nEMAIL:rosa@example.com\r\nEND:VCARD\r\n"
PDF = b"%PDF-1.4\n% fake but non-empty\n"


def keep(**fields):
    base = {"title": "", "textContent": "", "isTrashed": False, "isPinned": False, "isArchived": False, "color": "DEFAULT"}
    base.update(fields)
    return json.dumps(base).encode()


def takeout(tmp_path) -> Path:
    path = tmp_path / "takeout-001.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Takeout/Calendar/Family.ics", ICS)
        zf.writestr("Takeout/Contacts/All Contacts/All Contacts.vcf", VCF)
        zf.writestr("Takeout/Keep/Groceries.json", keep(title="Groceries", textContent=None,
                    listContent=[{"text": "milk", "isChecked": False}, {"text": "eggs", "isChecked": True}],
                    isPinned=True, color="YELLOW", labels=[{"name": "home stuff"}]))
        zf.writestr("Takeout/Keep/Idea.json", keep(title="Idea", textContent="Paint the fence", isArchived=True))
        zf.writestr("Takeout/Keep/Old.json", keep(title="Old", textContent="gone", isTrashed=True))
        zf.writestr("Takeout/Keep/Labels.txt", b"home stuff\n")
        zf.writestr("Takeout/Drive/Taxes/2025.pdf", PDF)
        zf.writestr("Takeout/Drive/Budget.xlsx", b"PK fake")
        zf.writestr("Takeout/Mail/All mail Including Spam and Trash.mbox", b"From x\n")
        zf.writestr("Takeout/Google Photos/2020/beach.jpg", b"\xff\xd8 fake jpeg")
        zf.writestr("../escape.pdf", PDF)
        zf.writestr("Takeout/Drive/zeros.txt", b"0" * (3 * 1024 * 1024))  # compresses ~1000x
    return path


@pytest.fixture
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'move.db'}", connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    made = sessionmaker(bind=engine)
    monkeypatch.setattr(cdb, "SessionLocal", made)
    monkeypatch.setattr("src.note_import.SessionLocal", made)
    library = tmp_path / "library"
    monkeypatch.setattr("routes.local_document_routes.DOCUMENT_FILES_DIR", str(library))
    monkeypatch.setattr("src.constants.DATA_DIR", str(tmp_path / "data"))
    imported_contacts = []
    monkeypatch.setattr("routes.contacts.contacts_routes._import_vcards",
                        lambda text: imported_contacts.append(text) or {"imported": text.count("BEGIN:VCARD")})
    return SimpleNamespace(made=made, tmp=tmp_path, library=library, contacts=imported_contacts)


def test_scan_lists_what_is_inside(world):
    summary = move_in.scan(str(takeout(world.tmp)), "takeout-001.zip").summary()
    assert summary["calendars"] == ["Takeout/Calendar/Family.ics"]
    assert summary["contacts"] == 1
    assert summary["keep_notes"] == 3  # trashed notes are dropped at import
    assert summary["files"] == 1       # the PDF; the zip-bomb text file is skipped
    assert summary["office"] == 1 and summary["mail"] == 1 and summary["photos"] == 1
    reasons = {s["name"]: s["reason"] for s in summary["skipped"]}
    assert reasons["Takeout/Drive/zeros.txt"] == "suspicious compression"
    assert any(r == "unusual file path" for r in reasons.values())
    assert "Takeout/Keep/Labels.txt" in reasons


def test_import_brings_everything_in_for_its_owner(world):
    report = move_in.run_import(str(takeout(world.tmp)), "takeout-001.zip", "rosa",
                                choose={"calendar": True, "contacts": True, "keep": True, "file": True}, is_admin=False)
    assert report["calendars"][0]["imported"] == 1 and report["calendars"][0]["calendar"] == "Family"
    assert report["notes"]["imported"] == 2
    assert report["files"]["imported"] == 1
    assert "only the admin can import them" in report["messages"][0]
    assert world.contacts == []  # members don't touch the shared address book
    db = world.made()
    try:
        cal = db.query(CalendarCal).one()
        assert cal.owner == "rosa" and db.query(CalendarEvent).one().summary == "Dentist"
        notes = {n.title: n for n in db.query(Note).all()}
        assert set(notes) == {"Groceries", "Idea"}
        assert notes["Groceries"].note_type == "checklist" and notes["Groceries"].pinned and notes["Groceries"].color == "yellow"
        items = [(i["text"], i["done"]) for i in json.loads(notes["Groceries"].items)]
        assert items == [("milk", False), ("eggs", True)]
        assert notes["Groceries"].tags == ["home-stuff"]
        assert notes["Idea"].archived and notes["Idea"].content == "Paint the fence"
        assert all(n.owner == "rosa" and not n.ai_memory_enabled for n in notes.values())
        files = db.query(DocumentFile).all()
        assert [(f.owner, f.filename) for f in files] == [("rosa", "2025.pdf")]
        assert (world.library / files[0].storage_name).read_bytes() == PDF
    finally:
        db.close()


def test_admin_imports_contacts_and_choices_are_respected(world):
    report = move_in.run_import(str(takeout(world.tmp)), "takeout-001.zip", "admin",
                                choose={"calendar": False, "contacts": True, "keep": False, "file": False}, is_admin=True)
    assert report["contacts"] == {"imported": 1}
    assert "Abuela Rosa" in world.contacts[0]
    assert report["calendars"] == [] and report["notes"] is None and report["files"]["imported"] == 0


def test_a_single_calendar_file_works_and_other_single_files_do_not(world):
    ics = world.tmp / "outlook.ics"
    ics.write_bytes(ICS)
    assert move_in.scan(str(ics), "outlook.ics").summary()["calendars"] == ["outlook.ics"]
    other = world.tmp / "notes.txt"
    other.write_bytes(b"hello")
    assert move_in.scan(str(other), "notes.txt").summary()["skipped"][0]["reason"].startswith("upload a ZIP")


def test_keep_conversion_is_bounded_and_clean():
    data = json.loads(move_in.keep_to_exodus([
        {"title": "x" * 900, "textContent": "t", "labels": [{"name": "a b  c"}, {"name": "a b  c"}]},
        {"title": "trash", "isTrashed": True},
    ]))
    assert data["format"] == "exodus.notes" and len(data["notes"]) == 1
    assert len(data["notes"][0]["title"]) == 500 and data["notes"][0]["tags"] == ["a-b-c"]


@pytest.fixture
def client(world, monkeypatch):
    monkeypatch.setattr("core.middleware.auth_disabled", lambda: False)
    monkeypatch.setattr(routes_mod, "_uploads", {})
    app = FastAPI()
    app.state.auth_manager = SimpleNamespace(is_configured=True, is_admin=lambda u: u == "admin")

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.current_user = request.headers.get("x-test-user")
        return await call_next(request)

    app.include_router(routes_mod.setup_move_in_routes())
    return TestClient(app, client=("203.0.113.7", 50000))


def upload(client, world, user="rosa"):
    data = takeout(world.tmp).read_bytes()
    return client.post("/api/move-in/scan", content=data,
                       headers={"x-test-user": user, "x-filename": "takeout-001.zip", "content-type": "application/zip"})


def test_scan_then_import_over_http(client, world):
    scanned = upload(client, world)
    assert scanned.status_code == 200, scanned.text
    body = scanned.json()
    assert body["summary"]["keep_notes"] == 3 and body["summary"]["contacts_need_admin"] is True
    stored = list((world.tmp / "data" / "move-in").iterdir())
    assert len(stored) == 1 and oct(stored[0].stat().st_mode & 0o777) == "0o600"
    # Someone else can't use this upload.
    assert client.post("/api/move-in/import", json={"token": body["token"]}, headers={"x-test-user": "mallory"}).status_code == 404
    result = client.post("/api/move-in/import", json={"token": body["token"], "files": False}, headers={"x-test-user": "rosa"})
    assert result.status_code == 200 and result.json()["notes"]["imported"] == 2 and result.json()["files"]["imported"] == 0
    assert list((world.tmp / "data" / "move-in").iterdir()) == []  # temporary file deleted
    assert client.post("/api/move-in/import", json={"token": body["token"]}, headers={"x-test-user": "rosa"}).status_code == 404


def test_cancel_and_size_limit(client, world, monkeypatch):
    token = upload(client, world).json()["token"]
    assert client.delete(f"/api/move-in/{token}", headers={"x-test-user": "mallory"}).status_code == 404
    assert client.delete(f"/api/move-in/{token}", headers={"x-test-user": "rosa"}).status_code == 200
    assert list((world.tmp / "data" / "move-in").iterdir()) == []
    monkeypatch.setattr(routes_mod, "MAX_UPLOAD_BYTES", 1000)
    too_big = upload(client, world)
    assert too_big.status_code == 413 and "2 GB parts" in too_big.json()["detail"]
    assert list((world.tmp / "data" / "move-in").iterdir()) == []
    assert client.post("/api/move-in/scan", content=b"x").status_code == 401


def test_wired():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "from routes.move_in_routes import setup_move_in_routes" in app
    override = (ROOT / "docker-compose.override.yml").read_text(encoding="utf-8")
    assert "./src/move_in.py:/app/src/move_in.py:ro" in override
    assert "./routes/move_in_routes.py:/app/routes/move_in_routes.py:ro" in override
    from src.ai_policy import allowed_without_ai
    assert allowed_without_ai("/api/move-in/scan", "POST")


def test_move_in_card_in_a_real_browser():
    import shutil
    import subprocess
    if not shutil.which("node") or not (ROOT / "node_modules" / "playwright").exists():
        pytest.skip("node with the playwright package is required (npm ci)")
    result = subprocess.run(["node", "tests/browser/moveIn.mjs"], cwd=ROOT,
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: move in card" in result.stdout


def test_move_in_card_is_wired():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    panel = html.split('data-settings-panel="account"', 1)[1].split('data-settings-panel=', 1)[0]
    assert 'id="move-in-card"' in panel and 'id="move-in-rows"' in panel
    settings = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")
    assert "mountMoveIn(byId('move-in-rows'))" in settings
    assert "'/static/js/settings/moveIn.js'" in (ROOT / "static" / "sw.js").read_text(encoding="utf-8")
