r"""Clock tool window (`static/js/clock.js` + `static/js/clock/`).

Covers the DOM-free logic every Clock tab relies on — time formatting, zone
offsets, sunrise/sunset, the lap colouring rule recovered from macOS Clock,
alarm scheduling and the Recents list — plus the lazy-panel wiring: Clock is
registered in `js/panels.js` and every module in its graph is precached for
offline use, like the image editor.
"""

import json
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_JS_DIR = _REPO / "static" / "js"
_TIME = (_JS_DIR / "clock" / "time.js").as_posix()
_STORE = (_JS_DIR / "clock" / "store.js").as_posix()
_PANELS = (_JS_DIR / "panels.js").as_posix()

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _run(js: str) -> dict:
    proc = subprocess.run(
        ["node", "--input-type=module"],
        input=textwrap.dedent(js), capture_output=True, text=True, cwd=str(_REPO), timeout=30,
        env={**os.environ, "TZ": "America/New_York"},
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip())


def test_display_formats_match_clock():
    out = _run(f"""
        const T = await import('{_TIME}');
        console.log(JSON.stringify({{
          sw: T.formatStopwatch(9170), swHour: T.formatStopwatch(3723456), swNeg: T.formatStopwatch(-5),
          cd: T.formatCountdown(1196), cdUp: T.formatCountdown(1195.2), cdHour: T.formatCountdown(3600),
          dur: T.durationLabel(630), durHour: T.durationLabel(3660), durZero: T.durationLabel(0),
          split: T.splitDuration(3725),
        }}));
    """)
    assert out == {
        "sw": "00:09.17", "swHour": "1:02:03.45", "swNeg": "00:00.00",
        "cd": "19:56", "cdUp": "19:56", "cdHour": "1:00:00",
        "dur": "10 min, 30 sec", "durHour": "1 hr, 1 min", "durZero": "0 sec",
        "split": {"h": 1, "m": 2, "s": 5},
    }


def test_lap_extrema_follow_clock_rule():
    # Only completed laps count, only from two laps up; the first fastest /
    # slowest lap wins a tie (MTAStopwatchLapTableViewController._updateLapExtrema).
    out = _run(f"""
        const {{ lapExtrema }} = await import('{_TIME}');
        console.log(JSON.stringify({{
          none: lapExtrema([]), one: lapExtrema([1500]),
          three: lapExtrema([2690, 1870, 2910]), tie: lapExtrema([1000, 1000, 2000, 2000]),
        }}));
    """)
    assert out["none"] == {"fastest": None, "slowest": None}
    assert out["one"] == {"fastest": None, "slowest": None}
    assert out["three"] == {"fastest": 1, "slowest": 2}
    assert out["tie"] == {"fastest": 0, "slowest": 2}


def test_world_clock_offsets_days_and_sun_times():
    out = _run(f"""
        const T = await import('{_TIME}');
        const d = new Date('2026-10-18T00:54:00Z');   // 8:54 PM in New York
        const sun = T.sunTimes(37.32, -122.03, 'America/Los_Angeles', d);
        const polar = T.sunTimes(78.22, 15.65, 'Arctic/Longyearbyen', new Date('2026-06-21T12:00:00Z'));
        console.log(JSON.stringify({{
          la: T.offsetLabel('America/Los_Angeles', d), kolkata: T.offsetLabel('Asia/Kolkata', d),
          tokyoDay: T.relativeDay('Asia/Tokyo', d), laDay: T.relativeDay('America/Los_Angeles', d),
          laTime: T.formatZoneTime('America/Los_Angeles', d, 'en-US'),
          sunrise: T.formatZoneTime('America/Los_Angeles', sun.sunrise, 'en-US'),
          sunset: T.formatZoneTime('America/Los_Angeles', sun.sunset, 'en-US'),
          polar, cupertinoDay: T.isDaylight(37.32, -122.03, d), nyDay: T.isDaylight(40.71, -74.01, d),
          termPoints: T.terminator(d, 10).points.length,
        }}));
    """)
    assert out["la"] == "-3 HRS"
    assert out["kolkata"] == "+9:30 HRS"
    assert out["tokyoDay"] == "Tomorrow" and out["laDay"] == "Today"
    assert out["laTime"] == "5:54 PM"
    # The real Clock.app showed 7:18 AM / 6:28 PM for Cupertino on this date.
    assert out["sunrise"] == "7:18 AM" and out["sunset"] == "6:28 PM"
    assert out["polar"] == {"sunrise": None, "sunset": None}
    assert out["cupertinoDay"] is True and out["nyDay"] is False
    assert out["termPoints"] == 37


def test_alarm_schedule_and_wording():
    out = _run(f"""
        const T = await import('{_TIME}');
        const fri9pm = new Date(2026, 9, 16, 21, 0);
        const next = (a) => T.nextAlarmDate(a, fri9pm)?.toString().slice(0, 21);
        console.log(JSON.stringify({{
          once: next({{ hour: 7, minute: 30, days: [] }}),
          weekdays: next({{ hour: 7, minute: 30, days: [1, 2, 3, 4, 5] }}),
          laterToday: next({{ hour: 22, minute: 0, days: [5] }}),
          detail: T.alarmDetail({{ label: '', days: [1, 2, 3, 4, 5] }}),
          labelled: T.alarmDetail({{ label: 'Gym', days: [0, 6] }}),
          some: T.repeatSummary([3, 1]), single: T.repeatSummary([2]), every: T.repeatSummary([0,1,2,3,4,5,6]),
          midnight: T.alarmTimeParts(0, 5), noon: T.alarmTimeParts(12, 0), h24: T.alarmTimeParts(7, 5, false),
        }}));
    """)
    assert out["once"] == "Sat Oct 17 2026 07:30"
    assert out["weekdays"] == "Mon Oct 19 2026 07:30"
    assert out["laterToday"] == "Fri Oct 16 2026 22:00"
    assert out["detail"] == "Alarm, weekdays"
    assert out["labelled"] == "Gym, weekends"
    assert out["some"] == "Mon Wed" and out["single"] == "every Tuesday" and out["every"] == "every day"
    assert out["midnight"] == {"time": "12:05", "period": "AM"}
    assert out["noon"] == {"time": "12:00", "period": "PM"}
    assert out["h24"] == {"time": "07:05", "period": ""}


def test_timer_presets_and_recents():
    out = _run(f"""
        const {{ TIMER_PRESETS }} = await import('{_TIME}');
        const S = await import('{_STORE}');
        const s = S.getState();
        S.pushRecentTimer(s, {{ duration: 1200, label: '', sound: 'chime' }});
        S.pushRecentTimer(s, {{ duration: 300, label: 'Tea', sound: 'bell' }});
        S.pushRecentTimer(s, {{ duration: 1200, label: ' ', sound: 'pulse' }});
        for (let i = 0; i < 30; i++) S.pushRecentTimer(s, {{ duration: 10 + i, label: '', sound: 'chime' }});
        console.log(JSON.stringify({{
          presets: TIMER_PRESETS.map(p => p.seconds),
          recentCount: s.recentTimers.length,
          firstIsNewest: s.recentTimers[0].duration,
          defaults: s.worldClocks.map(c => c.city),
          pending: S.hasPendingWork(s),
        }}));
    """)
    assert out["presets"] == [60, 120, 180, 240, 300, 600, 900, 1200, 1800, 2700, 3600, 7200]
    assert out["recentCount"] == 20
    assert out["firstIsNewest"] == 39
    assert out["defaults"] == ["Cupertino", "New York"]
    assert out["pending"] is False


def test_clock_is_a_registered_lazy_panel():
    out = _run(f"""
        const {{ panelNames }} = await import('{_PANELS}');
        console.log(JSON.stringify(panelNames()));
    """)
    assert "clock" in out


_STATIC_IMPORT = re.compile(
    r"""(?:^|\n)\s*(?:import\s+(?:[^;'"()]*?\s+from\s+)?|export\s+(?:\*|\{[^}]*\})\s+from\s+)['"]([^'"]+)['"]"""
)


def _clock_module_graph() -> set[str]:
    seen: set[str] = set()
    stack = ["clock.js"]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        source = (_JS_DIR / current).read_text(encoding="utf-8")
        for spec in _STATIC_IMPORT.findall(source):
            if spec.startswith("."):
                # Shared modules carry ?v= cache-bust queries; the file is the path.
                spec = spec.split("?", 1)[0]
                stack.append(os.path.normpath(os.path.join(os.path.dirname(current), spec)))
    return seen


def test_every_lazy_clock_file_is_precached_for_offline_use():
    sw = (_REPO / "static" / "sw.js").read_text(encoding="utf-8")
    block = re.search(r"const PANEL_PRECACHE = \[(.*?)\];", sw, re.S)
    assert block, "PANEL_PRECACHE not found in static/sw.js"
    precached = set(re.findall(r"'([^']+)'", block.group(1)))
    lazy_only = {m for m in _clock_module_graph() if m == "clock.js" or m.startswith("clock/")}
    lazy_only.add("clock/clock.css")  # linked at runtime by clock/dom.js
    missing = {f"/static/js/{m}" for m in lazy_only} - precached
    assert not missing, f"Clock files load lazily but are not in PANEL_PRECACHE: {sorted(missing)}"
