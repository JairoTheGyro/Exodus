"""Exodus translations (static/js/i18n.js, static/locales/*.json).

Wave 1 covers the sign-in page, Home and Settings Essentials in Spanish (Latin
America). Catalogs map exact English wording to a translation. The coverage
tests below read the visible text of the sign-in page and of the Essentials
Settings panels; a new English string there fails until it has a Spanish entry
(or is a name that stays as it is, listed in KEEP).
"""
import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "static" / "locales" / "es-419.json").read_text(encoding="utf-8"))
MESSAGES = CATALOG["messages"]
ESSENTIALS = {"services", "added-models", "integrations", "email", "appearance", "account"}
ATTRS = ("title", "aria-label", "placeholder", "alt")
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

# Names and fragments that are the same in every language.
KEEP = {
    "Exodus", "Aa", "/settings", "LLM", "proxy", "api",
    "Anthropic", "DeepSeek", "OpenAI", "GitHub Copilot", "ChatGPT Subscription", "Featherless.ai", "OpenRouter",
    "Ollama Cloud", "Groq", "Mistral", "Together AI", "Fireworks AI", "Google Gemini", "xAI Grok", "Z.AI (Zhipu)",
    "OpenCode Zen", "OpenCode Go", "Z.AI Coding Plan", "NVIDIA",
    "AI Workshop", "Code", "SearXNG", "ChromaDB", "ntfy", "Vaultwarden", "RAG", "Prompt",
}


class _Visible(HTMLParser):
    """Visible text and text attributes, filtered by a predicate on the open-tag stack."""

    def __init__(self, include):
        super().__init__(convert_charrefs=True)
        self.include, self.stack, self.out = include, [], []

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        stack = self.stack + [(tag, a)]
        if tag not in VOID:
            self.stack.append((tag, a))
        if self.include(stack):
            self.out += [a[k].strip() for k in ATTRS if re.search("[A-Za-z]{2}", a.get(k, ""))]

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        while self.stack and self.stack.pop()[0] != tag:
            pass

    def handle_data(self, data):
        text = re.sub(r"\s+", " ", data).strip()
        if text and re.search("[A-Za-z]{2}", text) and self.include(self.stack):
            self.out.append(text)


def _visible(path, include):
    parser = _Visible(include)
    parser.feed((ROOT / path).read_text(encoding="utf-8"))
    return list(dict.fromkeys(parser.out))


def _login_scope(stack):
    return any(t == "body" for t, _ in stack) and not any(t in ("script", "style", "select") for t, _ in stack)


def _settings_essentials(stack):
    if not any(a.get("id") == "settings-modal" for _, a in stack):
        return False
    for tag, a in stack:
        if tag in ("script", "style", "select", "option"):
            return False
        if "data-settings-advanced" in a or "admin-only" in a.get("class", "").split():
            return False
        panel = a.get("data-settings-panel")
        if panel is not None and panel not in ESSENTIALS:
            return False
    return True


def _missing(strings):
    return [s for s in strings if s not in MESSAGES and s not in KEEP]


def test_catalog_shape():
    assert CATALOG["language"] == "es-419"
    assert MESSAGES and all(isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in MESSAGES.items())
    for source, target in CATALOG["patterns"]:
        assert set(re.findall(r"\{[a-z_]+\}", source)) == set(re.findall(r"\{[a-z_]+\}", target))
    # Spanish (Latin America) wording, not Spain.
    joined = " ".join(MESSAGES.values()).lower()
    for spain_only in ("ordenador", "vosotros", "habéis"):
        assert spain_only not in joined


def test_sign_in_page_is_fully_translated():
    assert _missing(_visible("static/login.html", _login_scope)) == []


def test_settings_essentials_are_fully_translated():
    assert _missing(_visible("static/index.html", _settings_essentials)) == []


def _in_ids(*ids):
    def include(stack):
        return any(a.get("id") in ids for _, a in stack) and not any(t in ("script", "style") for t, _ in stack)
    return include


def test_sidebar_and_chat_plus_menu_are_fully_translated():
    assert _missing(_visible("static/index.html", _in_ids("sidebar", "overflow-menu"))) == []


def _literal_toasts():
    texts = []
    for path in list(ROOT.glob("static/*.js")) + list(ROOT.glob("static/js/**/*.js")):
        if "/lib/" in path.as_posix():
            continue
        source = path.read_text(encoding="utf-8")
        for m in re.finditer(r"""showToast\??\.?\(\s*(['"])((?:\\.|(?!\1).)*?)\1""", source):
            text = m.group(2).replace("\\'", "'").replace('\\"', '"').strip()
            if re.search("[A-Za-z]{3}", text):
                texts.append(text)
    return sorted(set(texts))


def test_toast_messages_are_almost_all_translated():
    # A hard 100% would fail every upstream catch-up that adds a toast; 95%
    # keeps gaps small. New Exodus toasts should be translated in their PR.
    toasts = _literal_toasts()
    missing = _missing(toasts)
    assert len(toasts) > 250
    assert len(missing) / len(toasts) <= 0.05, f"{len(missing)} of {len(toasts)} toasts untranslated, e.g. {missing[:10]}"


def test_wiring():
    index = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    login = (ROOT / "static" / "login.html").read_text(encoding="utf-8")
    assert '<script type="module" src="/static/js/i18nStart.js"></script>' in index
    assert '<script type="module" src="static/js/i18nStart.js"></script>' in login
    assert 'data-i18n-scope' in login and 'id="login-language"' in login
    assert 'id="settings-language"' in index.split('data-settings-panel="appearance"', 1)[1]
    home = (ROOT / "static" / "js" / "home.js").read_text(encoding="utf-8")
    assert "toLocaleDateString(globalThis.__exodusLocale," in home
    sw = (ROOT / "static" / "sw.js").read_text(encoding="utf-8")
    for path in ("/static/js/i18n.js", "/static/js/i18nStart.js", "/static/js/settings/languagePicker.js", "/static/locales/es-419.json"):
        assert f"'{path}'" in sw
    override = (ROOT / "docker-compose.override.yml").read_text(encoding="utf-8")
    for mount in ("./static/js/i18n.js:", "./static/js/i18nStart.js:", "./static/locales:"):
        assert mount in override


@pytest.mark.skipif(not shutil.which("node") or not (ROOT / "node_modules" / "playwright").exists(),
                    reason="node with the playwright package is required (npm ci)")
def test_translations_in_a_real_browser():
    result = subprocess.run(["node", "tests/browser/i18n.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: translations" in result.stdout
