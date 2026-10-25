"""Workspace look (Apple-like) and the Dock: js/apps/workspaceLook.js,
js/apps/dock.js, css/91-look-apple.css, Settings → Appearance → Workspace look."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_workspace_look_and_dock_in_a_real_browser():
    if not shutil.which("node") or not (ROOT / "node_modules" / "playwright").exists():
        pytest.skip("node with the playwright package is required (npm ci)")
    result = subprocess.run(["node", "tests/browser/workspaceLook.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: workspace look and dock" in result.stdout


def test_wired():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    # Set before the first paint, so the look doesn't flash in.
    head = html.split("</head>", 1)[0]
    assert "exodus-workspace-look-v1" in head and "r.dataset.uiLook = 'apple'" in head
    assert '<link rel="stylesheet" href="/static/css/91-look-apple.css?v=20260929csssplit">' in html
    panel = html.split('data-settings-panel="appearance"', 1)[1].split('data-settings-panel=', 1)[0]
    assert 'id="workspace-look-rows"' in panel
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "mountDock();" in app and "applyWorkspaceLook();" in app and "followWorkspaceLook();" in app
    settings = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")
    assert "mountWorkspaceLook(byId('workspace-look-rows'))" in settings
    sw = (ROOT / "static" / "sw.js").read_text(encoding="utf-8")
    for path in ("/static/js/apps/workspaceLook.js", "/static/js/apps/dock.js",
                 "/static/js/settings/workspaceLookSettings.js", "/static/css/91-look-apple.css?v=20260929csssplit"):
        assert f"'{path}'" in sw, path


def _split_selectors(text):
    """Split a selector list on top-level commas only (not inside :is(...))."""
    parts, depth, current = [], 0, ""
    for ch in text:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    return parts + [current]


def test_apple_look_only_applies_when_chosen_and_never_with_temple():
    css = (ROOT / "static" / "css" / "91-look-apple.css").read_text(encoding="utf-8")
    rules = [r.strip() for r in re.findall(r"([^{}]+)\{", re.sub(r"/\*.*?\*/", "", css, flags=re.S)) if r.strip()]
    for selector_list in rules:
        if selector_list.startswith("@media"):
            continue
        for selector in _split_selectors(selector_list):
            selector = selector.strip()
            if selector.startswith((".app-dock", ":root[data-dock-mode")) or selector in ("to", "from"):
                continue
            assert selector.startswith(':root[data-ui-look="apple"]') and ":not(.theme-temple)" in selector, selector


def test_dock_uses_only_existing_buttons_and_the_app_list():
    dock = (ROOT / "static" / "js" / "apps" / "dock.js").read_text(encoding="utf-8")
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    home = (ROOT / "static" / "js" / "home.js").read_text(encoding="utf-8")
    for button in re.findall(r"button: '([a-z-]+)'", dock):
        assert f'id="{button}"' in html or f"id='{button}'" in html or f"button.id='{button}'" in home, button
