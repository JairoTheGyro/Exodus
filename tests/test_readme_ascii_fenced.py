"""Regression guard for the README title presentation.

The original ASCII-art banner needed a code fence to preserve whitespace.
Keep the wordmark title identity and the historical ASCII-fencing guard.
"""
from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"

# Box-drawing rule from the legacy ASCII banner (the #1390 failure mode).
_RULE = "─" * 10


def _fenced_segments(text: str):
    """Return the segments of *text* that sit INSIDE ``` fences."""
    parts = text.split("```")
    # parts[0] is before the first fence, parts[1] is inside the first fence, ...
    return parts[1::2]


def test_readme_opens_with_wordmark_title():
    # Exodus: the README opens with the AGPL modification notice (Exodus is a
    # modified Odysseus), then keeps the original Odysseus README and wordmark.
    text = README.read_text(encoding="utf-8")
    head = "\n".join(text.splitlines()[:5])
    assert head.startswith("# Exodus") and "modified version of [Odysseus]" in head
    original = text.split("original Odysseus README", 1)[1]
    assert 'alt="Odysseus"' in "\n".join(original.splitlines()[:15]), "the original README keeps the Odysseus wordmark"


def test_reintroduced_ascii_banner_stays_fenced():
    # Defensive: if a box-drawing banner is ever added back, it must be fenced so
    # GitHub renders it monospace-as-typed (the original #1390 regression).
    text = README.read_text(encoding="utf-8")
    if _RULE not in text:
        return
    inside = "\n".join(_fenced_segments(text))
    assert _RULE in inside, "ASCII banner rule must be inside a ``` code fence"
