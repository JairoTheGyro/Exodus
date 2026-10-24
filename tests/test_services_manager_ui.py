"""Settings → System → Services and per-person app hiding (frontend)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def read(*parts):
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


@pytest.mark.skipif(not shutil.which("node") or not (ROOT / "node_modules" / "playwright").exists(),
                    reason="node with the playwright package is required (npm ci)")
def test_services_manager_and_app_hiding_in_a_real_browser():
    result = subprocess.run(
        ["node", "tests/browser/servicesManager.mjs"], cwd=ROOT,
        capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: services manager" in result.stdout


def test_services_card_is_in_the_system_panel_and_wired():
    html = read("static", "index.html")
    panel = html.split('data-settings-panel="system"', 1)[1].split('data-settings-panel=', 1)[0]
    assert 'id="services-manager-card"' in panel and 'id="services-manager-rows"' in panel
    settings = read("static", "js", "settings.js")
    assert "import { mountServicesManager } from './settings/servicesManager.js';" in settings
    assert "mountServicesManager(byId('services-manager-rows'))" in settings
    assert "'services'" in read("static", "js", "settings", "registry.js")
    assert "'/static/js/settings/servicesManager.js'" in read("static", "sw.js")


def test_sidebar_card_has_a_switch_for_every_app():
    html = read("static", "index.html")
    for key in ("tool-workshop", "tool-code", "local-services-section", "privacy-hub-section"):
        assert f'data-ui-key="{key}"' in html
    settings = read("static", "js", "settings.js")
    # Registry apps (Clock, Calculator, and any added later) get rows generated
    # from the registry instead of hand-written HTML.
    assert "import { APPS } from './apps/registry.js';" in settings
    assert "addAppVisibilityRows();" in settings
    assert "for (const app of APPS) UI_VIS_MAP[`tool-${app.id}`]" in read("static", "js", "ui_visibility.js")


def test_hidden_apps_follow_the_person_to_every_device():
    app = read("static", "app.js")
    save = app.split("function saveUIVis(state) {", 1)[1].split("\n  }", 1)[0]
    assert "syncUIVisToAccount(state);" in save
    assert "fetch('/api/prefs/ui-visibility', {\n      method: 'PUT'" in app
    init = app.split("(function initUIVisibility() {", 1)[1][:900]
    assert "fetch('/api/prefs/ui-visibility'" in init
    assert "applyUIVis(saved);" in init
