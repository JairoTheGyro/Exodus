from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
THEME_JS = (ROOT / "static/js/theme.js").read_text(encoding="utf-8")


def test_five_distinct_builtin_themes_are_available() -> None:
    expected = {
        "eclipse": "starfield-depth",
        "porcelain": "dots",
        "arcade": "synapse",
        "blueprint": "dots",
        "monolith": "perlin-flow",
    }

    for name, pattern in expected.items():
        assert f"{name}:" in THEME_JS
        assert re.search(rf"\b{name}:\s*'{re.escape(pattern)}'", THEME_JS)


def test_new_themes_define_complete_core_palettes() -> None:
    for name in ("eclipse", "porcelain", "arcade", "blueprint", "monolith"):
        definition = THEME_JS.split(f"{name}:", 1)[1].split("},", 1)[0]
        for color in ("bg", "fg", "panel", "border", "red"):
            assert f"{color}:" in definition


def test_retired_theme_names_are_replaced() -> None:
    # Exodus keeps paper/copper/lavender as themes (never remove features); the
    # upstream replacement map stays and applies only if a theme is removed.
    for name in ("paper:", "copper:", "lavender:"):
        assert re.search(rf"^\s*{name}\s*\{{", THEME_JS, re.M), name
    assert "!THEMES[obj.name]" in THEME_JS
    assert "paper: 'monolith'" in THEME_JS
    assert "copper: 'arcade'" in THEME_JS
    assert "lavender: 'porcelain'" in THEME_JS
