"""Exodus welcome setup for new accounts (static/js/welcome/welcomeSetup.js)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def read(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


@pytest.mark.skipif(not shutil.which("node") or not (ROOT / "node_modules" / "playwright").exists(),
                    reason="node with the playwright package is required (npm ci)")
def test_welcome_setup_in_a_real_browser():
    result = subprocess.run(["node", "tests/browser/welcomeSetup.mjs"], cwd=ROOT,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: welcome opens for new accounts only" in result.stdout


def test_welcome_is_wired():
    assert "import('./js/welcome/welcomeSetup.js').then(m => m.maybeStartWelcome())" in read("static", "app.js")
    html = read("static", "index.html")
    panel = html.split('data-settings-panel="account"', 1)[1].split('data-settings-panel=', 1)[0]
    assert 'id="welcome-setup-card"' in panel and 'id="welcome-setup-rerun"' in panel
    assert "await import('./welcome/welcomeSetup.js')" in read("static", "js", "settings.js")
    assert "'/static/js/welcome/welcomeSetup.js'" in read("static", "sw.js")


def test_welcome_reuses_the_settings_pieces_and_is_translated():
    source = read("static", "js", "welcome", "welcomeSetup.js")
    for module in ("languagePicker.js", "appLooks.js", "phoneAlerts.js"):
        assert f"../settings/{module}" in source
    # The window is a translation scope, so Spanish speakers see it in Spanish.
    assert "'data-i18n-scope': ''" in source
    # The AI step is the same "Your AI" card as Settings (it also sets AI-free mode).
    assert "../settings/aiChoice.js" in source and "mountAiChoice(rows" in source
