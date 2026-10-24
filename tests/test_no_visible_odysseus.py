"""Exodus: no new visible "Odysseus" product text.

Exodus is a modified Odysseus. The product name people see is "Exodus"; the
word "Odysseus" may only remain where it is deliberate (roadmap decision D17):

- legal credit to the Odysseus project (License Tracker, README, ACKNOWLEDGMENTS),
- the mythological hero (the "Odysseus, king of Ithaca" persona and a quote),
- internal names nobody sees: headers (``X-Odysseus-*``), storage keys, CSS and
  function names, user agents, calendar PRODIDs,
- legacy markers that recognise data written before the rename,
- prompts for Odysseus's own fine-tuned models (``_minimal_odysseus_*``), which
  were trained with that exact wording.

This scans the screens (``static/``) and every user- or model-facing Python
string (``src/``, ``routes/``, ``core/``, ``mcp_servers/``, ``app.py``),
skipping comments and docstrings. A new visible mention fails with its file and
line; add an ``ALLOWED`` entry only if it is one of the deliberate kinds above.
"""
from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORD = re.compile(r"\bOdysseus\b")

# Substrings that make an occurrence deliberate. Keep each one specific.
ALLOWED = (
    # Legal credit (License Tracker in index.html).
    'id="license-odysseus-title">Odysseus<',
    "Credit remains with the Odysseus project",
    "Odysseus is provided without warranty",
    "This growing list covers Odysseus,",
    # Names of Odysseus's own fine-tuned AI models (a model name, not the product).
    "Odysseus/Ajax model names",
    # The mythological hero, not the product.
    "king of Ithaca",
    "son of Laertes",
    "name: 'Odysseus',",
    # Internal names nobody sees.
    "X-Odysseus-",
    "Odysseus/1.0",
    "Odysseus-Webhook",
    "Odysseus ChatGPT Subscription",
    "-//Odysseus//",
    # Identity sent to AI providers, kept for compatibility (test_branding_compatibility).
    "X-OpenRouter-Title",
    # Legacy markers recognising data written before the rename.
    "LEGACY_AUTO_REPLY_MARKERS = ['Odysseus email auto reply']",
    '"Reminder (Odysseus):"',
)

FRONTEND_GLOBS = ("static/*.html", "static/*.js", "static/js/**/*.js", "static/js/**/*.mjs", "static/manifest.json")
PYTHON_DIRS = ("src", "routes", "core", "mcp_servers")


def _allowed(text: str) -> bool:
    return any(token in text for token in ALLOWED)


def _strip_js_comments(source: str) -> str:
    """Blank out // and /* */ comments while keeping line numbers."""
    out, i, n = [], 0, len(source)
    quote = None
    while i < n:
        ch = source[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(source[i + 1]); i += 2; continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"`":
            quote = ch; out.append(ch); i += 1; continue
        if source.startswith("//", i) and (i == 0 or source[i - 1] != ":"):
            end = source.find("\n", i)
            end = n if end == -1 else end
            i = end
            continue
        if source.startswith("/*", i):
            end = source.find("*/", i + 2)
            end = n if end == -1 else end + 2
            out.append("\n" * source.count("\n", i, end))
            i = end
            continue
        out.append(ch); i += 1
    return "".join(out)


def _frontend_hits() -> list[str]:
    hits = []
    seen = set()
    for pattern in FRONTEND_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            if path in seen or "/lib/" in path.as_posix():
                continue
            seen.add(path)
            source = path.read_text(encoding="utf-8", errors="replace")
            if path.suffix == ".html":
                source = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), source, flags=re.S)
            else:
                source = _strip_js_comments(source)
            for lineno, line in enumerate(source.splitlines(), 1):
                if WORD.search(line) and not _allowed(line):
                    hits.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()[:160]}")
    return hits


def _python_files():
    yield ROOT / "app.py"
    for directory in PYTHON_DIRS:
        yield from sorted((ROOT / directory).rglob("*.py"))


def _python_hits() -> list[str]:
    hits = []
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        if "Odysseus" not in source:
            continue
        tree = ast.parse(source)
        doc_lines: set[int] = set()
        for node in ast.walk(tree):
            # Prompts for Odysseus's fine-tuned models keep their trained wording.
            if isinstance(node, ast.FunctionDef) and node.name.startswith("_minimal_odysseus_"):
                doc_lines.update(range(node.lineno, node.end_lineno + 1))
            for stmt in getattr(node, "body", []) if isinstance(getattr(node, "body", None), list) else []:
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                    doc_lines.update(range(stmt.lineno, stmt.end_lineno + 1))
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type != tokenize.STRING and tokenize.tok_name.get(tok.type) != "FSTRING_MIDDLE":
                continue
            if tok.start[0] in doc_lines or not WORD.search(tok.string) or _allowed(tok.string):
                continue
            if _allowed(source.splitlines()[tok.start[0] - 1]):
                continue
            hits.append(f"{path.relative_to(ROOT)}:{tok.start[0]}: {tok.string.strip()[:160]}")
    return hits


def test_screens_show_no_odysseus_product_text():
    hits = _frontend_hits()
    assert not hits, "Visible 'Odysseus' text in the screens; say 'Exodus' instead:\n" + "\n".join(hits)


def test_server_and_ai_text_shows_no_odysseus_product_text():
    hits = _python_hits()
    assert not hits, "'Odysseus' in user- or model-facing server text; say 'Exodus' instead:\n" + "\n".join(hits)


def test_guard_catches_a_new_visible_mention(tmp_path):
    # The scanners must flag plain product text and ignore comments.
    js = "// Odysseus comment\nconst label = 'Open Odysseus settings';\n"
    stripped = _strip_js_comments(js)
    assert not WORD.search(stripped.splitlines()[0])
    assert WORD.search(stripped.splitlines()[1]) and not _allowed(stripped.splitlines()[1])
    assert _allowed("headers['X-Odysseus-Owner'] = owner")
