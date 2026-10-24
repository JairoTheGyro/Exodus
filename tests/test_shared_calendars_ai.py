"""Exodus shared spaces: the AI's calendar tool reads shared calendars.

The assistant can list calendars and events from local calendars shared in
the person's spaces (labelled as shared), but create, update and delete stay
on the person's own calendars, so text another member typed into a shared
event can't steer it into changing things.
"""
import json
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import CalendarCal, CalendarEvent
from src import spaces
from src.tools.calendar import do_manage_calendar

ROOT = Path(__file__).resolve().parents[1]
USERS = {"mom": {}, "dad": {}, "neighbor": {}}
WINDOW = {"start": "2026-11-01T00:00:00", "end": "2026-12-01T00:00:00"}


@pytest.fixture
def made(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'cal.db'}", connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    monkeypatch.setattr(spaces, "SessionLocal", factory)
    space = spaces.create_space("mom", "Family")["id"]
    spaces.add_member("mom", space, "dad", USERS)
    db = factory()
    db.add_all([
        CalendarCal(id="fam", owner="mom", name="Family", source="local", space_id=space),
        CalendarCal(id="momcal", owner="mom", name="Mom private", source="local"),
        CalendarCal(id="dadcal", owner="dad", name="Dad", source="local"),
    ])
    db.add_all([
        CalendarEvent(uid="e-fam", calendar_id="fam", summary="Soccer practice",
                      dtstart=datetime(2026, 11, 10, 17), dtend=datetime(2026, 11, 10, 18)),
        CalendarEvent(uid="e-mom", calendar_id="momcal", summary="Mom secret",
                      dtstart=datetime(2026, 11, 11, 9), dtend=datetime(2026, 11, 11, 10)),
        CalendarEvent(uid="e-dad", calendar_id="dadcal", summary="Dad gym",
                      dtstart=datetime(2026, 11, 12, 7), dtend=datetime(2026, 11, 12, 8)),
    ])
    db.commit()
    db.close()
    return factory


async def tool(owner, **args):
    return await do_manage_calendar(json.dumps(args), owner=owner)


async def test_the_assistant_sees_shared_calendars_and_events(made):
    listed = await tool("dad", action="list_calendars")
    names = {c["name"]: c["shared_by"] for c in listed["calendars"]}
    assert names["Family"] == "mom" and names["Dad"] is None
    assert "Mom private" not in names
    assert "shared by mom, read-only for the assistant" in listed["response"]

    events = await tool("dad", action="list_events", **WINDOW)
    summaries = [e["summary"] for e in events["events"]]
    assert summaries == ["Soccer practice", "Dad gym"]
    assert "[shared by mom; read-only for the assistant]" in events["response"]
    assert "Mom secret" not in events["response"]


async def test_outsiders_and_owners_see_only_what_they_should(made):
    neighbor = await tool("neighbor", action="list_events", **WINDOW)
    assert neighbor.get("events", []) == []
    mom = await tool("mom", action="list_events", **WINDOW)
    assert [e["summary"] for e in mom["events"]] == ["Soccer practice", "Mom secret"]
    assert "shared by" not in mom["response"]  # her own calendars


async def test_the_assistant_cannot_change_a_shared_calendar(made):
    created = await tool("dad", action="create_event", summary="Injected", dtstart="2026-11-13T10:00:00",
                         calendar="Family")
    assert created["exit_code"] == 1 and "shared by mom" in created["error"]
    for action in ("update_event", "delete_event"):
        result = await tool("dad", action=action, uid="e-fam", summary="Changed")
        assert result.get("exit_code") == 1, (action, result)
    db = made()
    try:
        event = db.get(CalendarEvent, "e-fam")
        assert event is not None and event.summary == "Soccer practice"
        assert db.query(CalendarEvent).filter(CalendarEvent.summary == "Injected").count() == 0
    finally:
        db.close()


async def test_the_assistant_still_manages_its_own_calendar(made):
    created = await tool("dad", action="create_event", summary="Dentist", dtstart="2026-11-14T10:00:00", calendar="Dad")
    assert created["exit_code"] == 0, created


def test_home_and_the_daily_brief_include_shared_calendars():
    # Home's agenda uses /api/calendar/events (shared since PR #80); the
    # morning brief now uses the same filter.
    home = (ROOT / "static" / "js" / "home.js").read_text(encoding="utf-8")
    assert "api('/api/calendar/events?'" in home
    brief = (ROOT / "src" / "builtin_actions.py").read_text(encoding="utf-8")
    assert "from routes.calendar_routes import _visible_calendar_filter" in brief
