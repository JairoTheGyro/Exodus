r"""Exodus built-in app registry, launcher and look hooks (`static/js/apps/`).

The registry is the one list of built-in apps: the Tools-menu entries, the
lazy loaders in `js/panels.js` and the background starts all come from it, and
`js/apps/looks.js` decides which look an app window gets.
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
_JS = _REPO / "static" / "js"
_APPS = _JS / "apps"
_REGISTRY = (_APPS / "registry.js").as_posix()
_LAUNCHER = (_APPS / "launcher.js").as_posix()
_LOOKS = (_APPS / "looks.js").as_posix()
_PANELS = (_JS / "panels.js").as_posix()

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# A minimal DOM: enough for launcher.js to find anchors, insert entries and
# attach click handlers, without a browser.
_FAKE_DOM = r"""
class El {
  constructor(tag, doc) { this.tag = tag; this.doc = doc; this.children = []; this.attrs = {}; this.dataset = {}; this.handlers = {}; this.className = ''; this.id = ''; this.textContent = ''; this.innerHTML = ''; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  append(...kids) { this.children.push(...kids); }
  addEventListener(name, fn) { (this.handlers[name] ||= []).push(fn); }
  async click() { for (const fn of this.handlers.click || []) await fn(); }
  after(node) { const list = this.doc.order; list.splice(list.indexOf(this) + 1, 0, node); }
}
class Doc {
  constructor(anchorIds) { this.order = anchorIds.map(id => { const e = new El('div', this); e.id = id; return e; }); }
  createElement(tag) { return new El(tag, this); }
  createElementNS(_, tag) { return new El(tag, this); }
  getElementById(id) { return this.order.find(e => e.id === id) || null; }
}
class Store { constructor(init = {}) { this.data = { ...init }; } getItem(k) { return k in this.data ? this.data[k] : null; } setItem(k, v) { this.data[k] = String(v); } }
"""


def _run(js: str):
    proc = subprocess.run(
        ["node", "--input-type=module"],
        input=_FAKE_DOM + textwrap.dedent(js), capture_output=True, text=True, cwd=str(_REPO), timeout=30,
        env=dict(os.environ),
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip())


def test_registry_lists_each_app_once_with_everything_the_launcher_needs():
    out = _run(f"""
        const {{ APPS, appById, appLoaders }} = await import('{_REGISTRY}');
        console.log(JSON.stringify({{
          ids: APPS.map(a => a.id),
          complete: APPS.every(a => a.name && a.description && a.menuAfter && a.icon && typeof a.load === 'function' && a.toggle),
          frozen: Object.isFrozen(APPS) && APPS.every(Object.isFrozen),
          loaders: Object.keys(appLoaders()),
          lookup: appById('calculator')?.name, missing: appById('nope'),
        }}));
    """)
    assert out["ids"] == ["clock", "calculator"]
    assert len(set(out["ids"])) == len(out["ids"])
    assert out["complete"] and out["frozen"]
    assert out["loaders"] == out["ids"]
    assert out["lookup"] == "Calculator" and out["missing"] is None


def test_panels_loader_includes_every_registered_app():
    out = _run(f"""
        const {{ APPS }} = await import('{_REGISTRY}');
        const {{ panelNames }} = await import('{_PANELS}');
        console.log(JSON.stringify({{ apps: APPS.map(a => a.id), panels: panelNames() }}));
    """)
    assert set(out["apps"]) <= set(out["panels"])
    assert "editor" in out["panels"]


def test_registered_modules_export_the_toggle_the_registry_names():
    # Static check: importing the app modules in Node would need a DOM.
    registry = (_APPS / "registry.js").read_text()
    for path, toggle in re.findall(r"load: \(\) => import\('\.\./([^']+)'\),\s*toggle: '(\w+)'", registry):
        source = (_JS / path).read_text()
        assert f"export function {toggle}(" in source, f"{path} must export {toggle}()"


def test_launcher_builds_menu_entries_after_their_anchor_and_opens_the_app():
    out = _run(f"""
        const {{ installApps }} = await import('{_LAUNCHER}');
        const {{ APPS }} = await import('{_REGISTRY}');
        globalThis.document = new Doc(['tool-calendar-btn', 'tool-compare-btn', 'tool-skills-btn']);
        const opened = [], loaded = [];
        const fake = id => ({{ [APPS.find(a => a.id === id).toggle]: () => opened.push(id) }});
        const installed = installApps({{ doc: document, apps: APPS, schedule: () => {{}},
          loadPanel: async id => {{ loaded.push(id); return fake(id); }} }});
        const order = document.order.map(e => e.id);
        const calc = document.getElementById('tool-calculator-btn');
        await calc.click();
        console.log(JSON.stringify({{ installed, order, opened, loaded,
          label: calc.attrs['aria-label'], cls: calc.className, name: calc.children[1].textContent }}));
    """)
    assert out["installed"] == ["clock", "calculator"]
    assert out["order"] == ["tool-calendar-btn", "tool-clock-btn", "tool-compare-btn", "tool-skills-btn", "tool-calculator-btn"]
    assert out["opened"] == ["calculator"] and out["loaded"] == ["calculator"]
    assert out["label"] == "Calculator — basic, scientific and programmer, with unit conversion"
    assert out["cls"] == "list-item" and out["name"] == "Calculator"


def test_launcher_reuses_an_existing_entry_skips_missing_anchors_and_reports_load_failures():
    out = _run(f"""
        const {{ installApps }} = await import('{_LAUNCHER}');
        const {{ APPS }} = await import('{_REGISTRY}');
        globalThis.document = new Doc(['tool-clock-btn']);
        const toasts = [];
        const errors = []; console.error = (...a) => errors.push(a[0]);
        const installed = installApps({{ doc: document, apps: APPS, schedule: () => {{}}, toast: m => toasts.push(m),
          loadPanel: async () => {{ throw new Error('offline'); }} }});
        await document.getElementById('tool-clock-btn').click();
        console.log(JSON.stringify({{ installed, count: document.order.length, toasts, errors }}));
    """)
    assert out["installed"] == ["clock"]  # no Skills anchor, so no Calculator entry
    assert out["count"] == 1  # the existing Clock entry was reused, not duplicated
    assert out["toasts"] == ["Clock could not load. Check your connection and try again."]
    assert out["errors"] == ["Clock failed to load"]


def test_clock_background_start_only_runs_with_saved_alarms_or_timers():
    out = _run(f"""
        const {{ installApps }} = await import('{_LAUNCHER}');
        const {{ APPS }} = await import('{_REGISTRY}');
        const run = async saved => {{
          globalThis.localStorage = new Store(saved ? {{ 'odysseus-clock-v1': JSON.stringify(saved) }} : {{}});
          const doc = new Doc(['tool-calendar-btn', 'tool-skills-btn']);
          const started = [], jobs = [];
          installApps({{ doc, apps: APPS, schedule: fn => jobs.push(fn),
            loadPanel: async id => ({{ startClockBackground: () => started.push(id) }}) }});
          for (const job of jobs) await job();
          return started;
        }};
        console.log(JSON.stringify({{
          none: await run(null),
          idle: await run({{ alarms: [{{ enabled: false }}], timers: [] }}),
          alarm: await run({{ alarms: [{{ enabled: true }}], timers: [] }}),
          timer: await run({{ alarms: [], timers: [{{ endsAt: 123 }}] }}),
        }}));
    """)
    assert out == {"none": [], "idle": [], "alarm": ["clock"], "timer": ["clock"]}


def test_look_resolution_prefers_the_app_then_the_workspace_then_the_default():
    out = _run(f"""
        const L = await import('{_LOOKS}');
        const prefs = (workspace, apps = {{}}) => ({{ workspace, apps }});
        console.log(JSON.stringify({{
          default: L.resolveLook('clock', prefs(null)),
          workspace: L.resolveLook('clock', prefs('exodus')),
          app: L.resolveLook('clock', prefs('apple', {{ clock: 'exodus' }})),
          other: L.resolveLook('calculator', prefs('apple', {{ clock: 'exodus' }})),
          unknownFallsBack: L.resolveLook('clock', prefs('windows', {{ clock: 'nope' }})),
          looks: Object.keys(L.LOOKS), def: L.DEFAULT_LOOK,
        }}));
    """)
    assert out["default"] == "apple" and out["workspace"] == "exodus"
    assert out["app"] == "exodus" and out["other"] == "apple"
    assert out["unknownFallsBack"] == "apple"
    assert out["looks"] == ["apple", "exodus"] and out["def"] == "apple"


def test_set_look_saves_the_choice_and_updates_open_windows():
    out = _run(f"""
        const L = await import('{_LOOKS}');
        const storage = new Store();
        const events = [];
        const win = {{ dataset: {{}}, ownerDocument: null }};
        const doc = {{
          head: {{ append: () => {{}} }}, querySelector: () => null, createElement: () => ({{ dataset: {{}} }}),
          querySelectorAll: () => [win], dispatchEvent: e => events.push(e.detail),
        }};
        win.ownerDocument = doc;
        globalThis.CustomEvent ||= class {{ constructor(t, o) {{ this.type = t; this.detail = o.detail; }} }};
        const first = L.applyLook(win, 'calculator', {{ storage }});
        L.setLook({{ look: 'exodus' }}, {{ storage, doc }});
        const afterWorkspace = win.dataset.look;
        L.setLook({{ app: 'calculator', look: 'apple' }}, {{ storage, doc }});
        const afterApp = win.dataset.look;
        L.setLook({{ app: 'calculator', look: null }}, {{ storage, doc }});
        let bad = null; try {{ L.setLook({{ look: 'nope' }}, {{ storage, doc }}); }} catch (e) {{ bad = e.name; }}
        console.log(JSON.stringify({{ first, afterWorkspace, afterApp, cleared: win.dataset.look,
          id: win.dataset.appLookId, saved: JSON.parse(storage.getItem(L.LOOK_STORAGE_KEY)), events, bad }}));
    """)
    assert out["first"] == "apple" and out["id"] == "calculator"
    assert out["afterWorkspace"] == "exodus" and out["afterApp"] == "apple" and out["cleared"] == "exodus"
    assert out["saved"] == {"workspace": "exodus", "apps": {}}
    assert out["events"][0] == {"app": None, "look": "exodus"}
    assert out["bad"] == "TypeError"


def test_app_css_reads_look_settings_with_native_fallbacks_only():
    defined = set(re.findall(r"(--look-[\w-]+):", (_APPS / "looks.css").read_text()))
    for css in (_JS / "calculator" / "calculator.css", _JS / "clock" / "clock.css"):
        text = css.read_text()
        uses = re.findall(r"var\((--look-[\w-]+)(,?)", text)
        assert uses, f"{css.name} should read the shared look settings"
        # Every read keeps the app's own value as a fallback, so the Apple-like
        # look (which sets nothing) renders exactly as before.
        assert all(comma for _, comma in uses), f"{css.name} has a --look-* read without a fallback"
        assert {name for name, _ in uses} <= defined, f"{css.name} reads a setting no look defines"


def test_apps_apply_their_look_and_assets_are_precached_and_mounted():
    assert "applyLook(modal, 'calculator')" in (_JS / "calculator" / "index.js").read_text()
    assert "applyLook(modal, 'clock')" in (_JS / "clock.js").read_text()
    sw = (_REPO / "static" / "sw.js").read_text()
    for name in ("registry.js", "launcher.js", "looks.js", "looks.css"):
        assert f"'/static/js/apps/{name}'" in sw
    assert "./static/js/apps:/app/static/js/apps:ro" in (_REPO / "docker-compose.override.yml").read_text()
    html = (_REPO / "static" / "index.html").read_text()
    assert 'id="tool-clock-btn"' not in html and 'id="tool-calculator-btn"' not in html, \
        "built-in app menu entries come from the registry, not index.html"
