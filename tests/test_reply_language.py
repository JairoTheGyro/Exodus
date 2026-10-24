"""Exodus: the AI replies in the language the person chose (src/reply_language.py)."""
from pathlib import Path

import pytest

from src.reply_language import REPLY_LANGUAGE_MARKER, reply_language, reply_language_instruction, reply_language_message

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("prefs", [None, {}, {"language": "en"}, {"language": "fr"}, {"language": 7}, "es-419"])
def test_english_and_unknown_choices_add_nothing(prefs):
    assert reply_language(prefs) is None
    assert reply_language_instruction(prefs) is None
    assert reply_language_message(prefs) is None


def test_spanish_choice_asks_for_latin_american_spanish():
    message = reply_language_message({"language": "es-419"})
    assert message["role"] == "system"
    text = message["content"]
    assert text.startswith(REPLY_LANGUAGE_MARKER)
    assert "Latin American Spanish" in text and "es-419" in text
    assert "unless they explicitly ask for a different language" in text
    assert "Keep code, commands, file names, URLs and quoted text exactly as they are." in text
    # Stable wording, so the reused prompt prefix stays identical turn to turn.
    assert reply_language_message({"language": "es-419"}) == message


def _harness(monkeypatch, prefs, preset_prompt="You are Odysseus."):
    from tests.test_kv_cache_invalidation_2927 import _build_context_harness, _install_chat_helpers_stubs

    chat_helpers = _install_chat_helpers_stubs(monkeypatch)
    sess, request, handler, processor = _build_context_harness(monkeypatch, chat_helpers, history=[])
    monkeypatch.setattr(chat_helpers, "load_prefs_for_user", lambda user: prefs)
    if preset_prompt is None:
        monkeypatch.setattr(chat_helpers, "extract_preset", lambda chat_handler, preset_id: chat_helpers.PresetInfo(
            temperature=0.7, max_tokens=1024, system_prompt=None, character_name=None,
        ))
    return chat_helpers, sess, request, handler, processor


async def _build(chat_helpers, sess, request, handler, processor):
    return await chat_helpers.build_chat_context(
        sess=sess, request=request, chat_handler=handler, chat_processor=processor,
        message="hola", session_id="s",
    )


def _language_lines(messages):
    return [m for m in messages if m.get("role") == "system" and str(m.get("content", "")).startswith(REPLY_LANGUAGE_MARKER)]


@pytest.mark.asyncio
async def test_chat_context_includes_the_language_after_the_persona(monkeypatch):
    harness = _harness(monkeypatch, {"language": "es-419"})
    ctx = await _build(*harness)
    assert len(_language_lines(ctx.preface)) == 1
    assert len(_language_lines(ctx.messages)) == 1
    # The preset/persona prompt stays first; the language follows it.
    preset_index = next(i for i, m in enumerate(ctx.preface) if m.get("content") == "You are Odysseus.")
    assert _language_lines([ctx.preface[preset_index + 1]])


@pytest.mark.asyncio
async def test_chat_context_without_a_persona_puts_the_language_first(monkeypatch):
    harness = _harness(monkeypatch, {"language": "es-419"}, preset_prompt=None)
    ctx = await _build(*harness)
    assert _language_lines([ctx.preface[0]])


@pytest.mark.asyncio
async def test_english_chat_context_is_unchanged(monkeypatch):
    harness = _harness(monkeypatch, {"language": "en"})
    ctx = await _build(*harness)
    assert _language_lines(ctx.messages) == []


def test_agent_full_inventory_path_keeps_the_language():
    source = (ROOT / "src" / "agent_loop.py").read_text(encoding="utf-8")
    block = source.split("        if _full_inventory_mode:", 1)[1].split("        elif normalized_external_tool_schemas:", 1)[0]
    assert "from src.reply_language import REPLY_LANGUAGE_MARKER" in block
    assert ".startswith(REPLY_LANGUAGE_MARKER)" in block
    assert ") + _reply_language}" in block
