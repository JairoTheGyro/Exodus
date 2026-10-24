"""Exodus on phones: home-screen install details and phone-size checks."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def read(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


@pytest.mark.skipif(not shutil.which("node") or not (ROOT / "node_modules" / "playwright").exists(),
                    reason="node with the playwright package is required (npm ci)")
def test_phone_checks_in_a_real_browser():
    result = subprocess.run(["node", "tests/browser/phoneReady.mjs"], cwd=ROOT,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: phone sign-in fits" in result.stdout


def test_manifest_installs_as_an_app_with_real_icons():
    manifest = json.loads(read("static", "manifest.json"))
    assert manifest["display"] == "standalone" and manifest["start_url"] == "/"
    assert manifest["name"] == "Exodus" and len(manifest["short_name"]) <= 12
    purposes = {}
    for icon in manifest["icons"]:
        path = ROOT / "static" / icon["src"]
        width, height = (int(n) for n in icon["sizes"].split("x"))
        with Image.open(path) as image:
            assert image.size == (width, height), icon["src"]
        purposes.setdefault(icon["purpose"], []).append(width)
    assert 192 in purposes["any"] and 512 in purposes["any"]
    assert 512 in purposes["maskable"]  # Android's adaptive icon


@pytest.mark.parametrize("page", ["index.html", "login.html"])
def test_both_entry_pages_install_as_an_app(page):
    html = read("static", page)
    for tag in ('name="apple-mobile-web-app-capable" content="yes"',
                'name="apple-mobile-web-app-title" content="Exodus"',
                'name="mobile-web-app-capable" content="yes"',
                'rel="apple-touch-icon"', 'rel="manifest"', 'name="theme-color"'):
        assert tag in html, (page, tag)
    # iOS: no zoom when a field is focused, pinch-zoom still allowed.
    assert "maximum-scale=1" in html and "isIOS" in html


def test_welcome_layers_above_homes_first_run_screen():
    css = read("static", "css", "90-exodus.css")
    assert "body.exodus-welcome-open #home-choice { display: none !important; }" in css
    assert "#exodus-welcome { visibility: visible !important; }" in css
    assert ".exodus-welcome { position: fixed; inset: 0; z-index: 16000;" in css
    assert "#home-choice { position:fixed; inset:0; z-index:15000;" in read("static", "home.css")
