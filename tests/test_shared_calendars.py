"""Exodus shared spaces, part 2: shared calendars (routes/calendar_routes.py).

Members of a space see a local calendar shared there and can add, edit and
delete its events. Only the owner can rename, recolour, delete, export or
re-share the calendar. Everyone else sees nothing.
"""
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import CalendarCal
import routes.calendar_routes as cr
import routes.space_routes as sr
from src import spaces

PEER = ("203.0.113.7", 54321)
USERS = {"admin": {"is_admin": True}, "mom": {}, "dad": {}, "neighbor": {}}
WINDOW = {"start": "2026-11-01T00:00:00", "end": "2026-12-01T00:00:00"}


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
    engine = create_engine(f"sqlite:///{tmp_path / 'cal.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    made = sessionmaker(bind=engine)
    monkeypatch.setattr(cr, "SessionLocal", made)
    monkeypatch.setattr(spaces, "SessionLocal", made)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.delenv("LOCALHOST_BYPASS", raising=False)
    return made


@pytest.fixture
def client(factory):
    app = FastAPI()
    app.state.auth_manager = SimpleNamespace(
        is_configured=True, users=USERS, is_admin=lambda u: bool(USERS.get(u, {}).get("is_admin")))
    app.include_router(cr.setup_calendar_routes())
    app.include_router(sr.setup_space_routes())
    transport = httpx.ASGITransport(app=Identity(app), client=PEER)
    return httpx.AsyncClient(transport=transport, base_url="http://cal.test")


def as_(user):
    return {"x-test-user": user}


async def family_calendar(c):
    """mom shares a "Family" calendar in the Family space (dad is a member)."""
    space = (await c.post("/api/spaces", json={"name": "Family"}, headers=as_("mom"))).json()["id"]
    await c.post(f"/api/spaces/{space}/members", json={"username": "dad"}, headers=as_("mom"))
    cal = (await c.post("/api/calendar/calendars", params={"name": "Family", "color": "#4caf50"}, headers=as_("mom"))).json()["id"]
    shared = await c.put(f"/api/calendar/calendars/{cal}", params={"space_id": space}, headers=as_("mom"))
    assert shared.status_code == 200, shared.text
    return space, cal


async def event(c, user, cal, summary, day="2026-11-10"):
    response = await c.post("/api/calendar/events", json={
        "summary": summary, "dtstart": f"{day}T10:00:00", "dtend": f"{day}T11:00:00", "calendar_href": cal,
    }, headers=as_(user))
    assert response.status_code == 200, response.text
    return response.json()["uid"]


async def summaries(c, user):
    events = (await c.get("/api/calendar/events", params=WINDOW, headers=as_(user))).json()["events"]
    return sorted(e["summary"] for e in events)


async def test_members_see_and_use_a_shared_calendar(client):
    async with client as c:
        space, cal = await family_calendar(c)
        await event(c, "mom", cal, "Dentist")
        dads = await event(c, "dad", cal, "Soccer")  # members can add events

        listed = (await c.get("/api/calendar/calendars", headers=as_("dad"))).json()["calendars"]
        family = next(x for x in listed if x["href"] == cal)
        assert family["mine"] is False and family["owner"] == "mom" and family["space_id"] == space
        assert any(x["mine"] for x in listed)  # dad's own default calendar is still there

        assert await summaries(c, "mom") == ["Dentist", "Soccer"]
        assert await summaries(c, "dad") == ["Dentist", "Soccer"]
        assert await summaries(c, "neighbor") == []

        # Members edit and delete events in it.
        assert (await c.put(f"/api/calendar/events/{dads}", json={"summary": "Soccer final"}, headers=as_("dad"))).status_code == 200
        assert (await c.get(f"/api/calendar/events/{dads}", headers=as_("mom"))).json()["event"]["summary"] == "Soccer final"
        assert (await c.delete(f"/api/calendar/events/{dads}", headers=as_("dad"))).status_code == 200
        assert await summaries(c, "mom") == ["Dentist"]


async def test_outsiders_get_nothing(client):
    async with client as c:
        _, cal = await family_calendar(c)
        uid = await event(c, "mom", cal, "Dentist")
        assert (await c.get(f"/api/calendar/events/{uid}", headers=as_("neighbor"))).status_code == 404
        assert (await c.put(f"/api/calendar/events/{uid}", json={"summary": "x"}, headers=as_("neighbor"))).status_code == 404
        assert (await c.delete(f"/api/calendar/events/{uid}", headers=as_("neighbor"))).status_code == 404
        bad = await c.post("/api/calendar/events", json={"summary": "x", "dtstart": "2026-11-10T10:00:00", "calendar_href": cal}, headers=as_("neighbor"))
        assert bad.status_code == 404
        assert all(x["href"] != cal for x in (await c.get("/api/calendar/calendars", headers=as_("neighbor"))).json()["calendars"])


async def test_only_the_owner_manages_the_calendar(client):
    async with client as c:
        space, cal = await family_calendar(c)
        assert (await c.put(f"/api/calendar/calendars/{cal}", params={"name": "Mine now"}, headers=as_("dad"))).status_code == 404
        assert (await c.put(f"/api/calendar/calendars/{cal}", params={"space_id": ""}, headers=as_("dad"))).status_code == 404
        assert (await c.delete(f"/api/calendar/calendars/{cal}", headers=as_("dad"))).status_code == 404
        assert (await c.get(f"/api/calendar/export/{cal}", headers=as_("dad"))).status_code == 404
        # The owner takes it back: members lose it.
        await event(c, "mom", cal, "Dentist")
        assert (await c.put(f"/api/calendar/calendars/{cal}", params={"space_id": ""}, headers=as_("mom"))).status_code == 200
        assert await summaries(c, "dad") == []


async def test_sharing_rules(client, factory):
    async with client as c:
        space, _ = await family_calendar(c)
        # Only into spaces you belong to.
        own = (await c.post("/api/calendar/calendars", params={"name": "N"}, headers=as_("neighbor"))).json()["id"]
        assert (await c.put(f"/api/calendar/calendars/{own}", params={"space_id": space}, headers=as_("neighbor"))).status_code == 404
        # Synced (CalDAV) calendars stay personal.
        db = factory()
        try:
            db.add(CalendarCal(id="dav", owner="mom", name="Work", source="caldav"))
            db.commit()
        finally:
            db.close()
        response = await c.put("/api/calendar/calendars/dav", params={"space_id": space}, headers=as_("mom"))
        assert response.status_code == 400 and "can't be shared" in response.json()["detail"]


async def test_leaving_or_deleting_the_space_returns_calendars(client):
    async with client as c:
        space, cal = await family_calendar(c)
        await event(c, "mom", cal, "Dentist")
        dad_cal = (await c.post("/api/calendar/calendars", params={"name": "Dad"}, headers=as_("dad"))).json()["id"]
        await c.put(f"/api/calendar/calendars/{dad_cal}", params={"space_id": space}, headers=as_("dad"))
        await event(c, "dad", dad_cal, "Gym")
        assert await summaries(c, "mom") == ["Dentist", "Gym"]
        meta = (await c.get("/api/spaces", headers=as_("mom"))).json()["spaces"][0]
        assert meta["calendar_count"] == 2

        assert (await c.delete(f"/api/spaces/{space}/members/dad", headers=as_("dad"))).status_code == 200
        assert await summaries(c, "mom") == ["Dentist"]
        assert await summaries(c, "dad") == ["Gym"]

        assert (await c.delete(f"/api/spaces/{space}", headers=as_("mom"))).status_code == 200
        assert await summaries(c, "mom") == ["Dentist"]
        listed = (await c.get("/api/calendar/calendars", headers=as_("mom"))).json()["calendars"]
        assert next(x for x in listed if x["href"] == cal)["space_id"] is None


def test_existing_databases_get_the_calendar_space_column(tmp_path, monkeypatch):
    import sqlite3
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE calendars (id VARCHAR PRIMARY KEY, owner VARCHAR, name VARCHAR)")
    conn.execute("INSERT INTO calendars VALUES ('c1', 'mom', 'Home')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{path}")
    cdb._migrate_add_calendar_space_id()
    cdb._migrate_add_calendar_space_id()
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT name, space_id FROM calendars").fetchall() == [("Home", None)]
    finally:
        conn.close()


def test_calendar_ui_is_wired():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    calendar = (root / "static" / "js" / "calendar.js").read_text(encoding="utf-8")
    assert "from './calendar/spaces.js';" in calendar
    assert "_loadCalSpaces().then(_decorateSpaces);" in calendar
    assert "'/static/js/calendar/spaces.js'" in (root / "static" / "sw.js").read_text(encoding="utf-8")
