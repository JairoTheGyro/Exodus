"""Settings → Appearance → App look (static/js/settings/appLooks.js)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not shutil.which("node") or not (ROOT / "node_modules" / "playwright").exists(),
                    reason="node with the playwright package is required (npm ci)")
def test_app_look_picker_in_a_real_browser():
    result = subprocess.run(
        ["node", "tests/browser/appLookPicker.mjs"], cwd=ROOT,
        capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: app look picker" in result.stdout


def test_picker_is_wired_into_appearance_settings():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    panel = html.split('data-settings-panel="appearance"', 1)[1].split('data-settings-panel=', 1)[0]
    assert 'id="app-look-card"' in panel and 'id="app-look-rows"' in panel
    settings = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")
    assert "import { mountAppLookPicker } from './settings/appLooks.js';" in settings
    assert "if (tab === 'appearance') { const rows = byId('app-look-rows'); if (rows) mountAppLookPicker(rows); }" in settings
    registry = (ROOT / "static" / "js" / "settings" / "registry.js").read_text(encoding="utf-8")
    assert "'look', 'app look', 'style'" in registry
    assert "'/static/js/settings/appLooks.js'" in (ROOT / "static" / "sw.js").read_text(encoding="utf-8")
