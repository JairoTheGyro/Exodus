"""Exodus: answer in the language each person chose.

The language is the person's interface choice (Settings → Appearance →
Language, saved as the ``language`` preference by static/js/i18n.js). English
adds nothing, so English conversations and their cached prompt prefixes are
unchanged. The instruction is stable for a person, so it does not disturb the
reused prompt prefix between turns either.
"""
from __future__ import annotations

from typing import Mapping, Optional

# Start of the instruction; lets prompt paths that rebuild their own system
# message carry it over (see src/agent_loop.py).
REPLY_LANGUAGE_MARKER = "Reply language:"

LANGUAGE_NAMES = {
    "es-419": "Latin American Spanish",
}


def reply_language(prefs: Optional[Mapping]) -> Optional[str]:
    """The chosen non-English language code, or None for English/unknown."""
    if not isinstance(prefs, Mapping):
        return None
    code = prefs.get("language")
    return code if isinstance(code, str) and code in LANGUAGE_NAMES else None


def reply_language_instruction(prefs: Optional[Mapping]) -> Optional[str]:
    code = reply_language(prefs)
    if not code:
        return None
    name = LANGUAGE_NAMES[code]
    return (
        f"{REPLY_LANGUAGE_MARKER} the person using Exodus chose {name} ({code}) as their language. "
        f"Write every reply in {name}, even when they write in another language and when tools, "
        "documents, emails or search results are in English, unless they explicitly ask for a "
        "different language. Keep code, commands, file names, URLs and quoted text exactly as they are."
    )


def reply_language_message(prefs: Optional[Mapping]) -> Optional[dict]:
    instruction = reply_language_instruction(prefs)
    return {"role": "system", "content": instruction} if instruction else None
