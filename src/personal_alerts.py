"""Exodus private phone alerts: one ntfy topic per account.

ntfy topics are the only secret: anyone who knows a topic's name can read it.
So every account gets its own long random topic, created the first time it is
needed and kept in that person's account preferences (an account rename
carries it along). Reminders and alerts for an account go only there.

Single-user installs (no accounts) keep the installation-wide topic.
"""
from __future__ import annotations

import os
import re
import secrets
from typing import Optional

PREF_KEY = "exodus_ntfy_topic"
TOPIC_RE = re.compile(r"^exodus-[A-Za-z0-9_-]{20,40}$")


def _new_topic() -> str:
    return "exodus-" + secrets.token_urlsafe(18)  # 24 chars, about 144 bits


def _load(owner: str) -> dict:
    from routes.prefs_routes import _load_for_user
    return _load_for_user(owner) or {}


def _save(owner: str, prefs: dict) -> None:
    from routes.prefs_routes import _save_for_user
    _save_for_user(owner, prefs)


# Placeholder owner used for calendar rows when there are no accounts.
_SINGLE_USER_OWNERS = {"owner@localhost"}


def has_accounts() -> bool:
    """True when people sign in with their own accounts (not a single-user install)."""
    from src.owner_identity import auth_disabled
    if auth_disabled():
        return False
    try:
        from core.auth import AuthManager
        manager = AuthManager()
        return bool(getattr(manager, "is_configured", False) and manager.users)
    except Exception:
        return False


def personal_topic(owner: Optional[str], create: bool = True) -> Optional[str]:
    """The account's private topic; created on first use. None without an
    owner or on single-user installs (they keep the shared topic)."""
    fallback = os.getenv("ODYSSEUS_FALLBACK_OWNER", "owner@localhost")
    if not owner or owner in _SINGLE_USER_OWNERS or owner == fallback or not has_accounts():
        return None
    prefs = _load(owner)
    topic = prefs.get(PREF_KEY)
    if isinstance(topic, str) and TOPIC_RE.fullmatch(topic):
        return topic
    if not create:
        return None
    topic = _new_topic()
    prefs[PREF_KEY] = topic
    _save(owner, prefs)
    return topic


def reset_topic(owner: str) -> str:
    """Give the account a fresh topic (e.g. if the old one was shared by mistake)."""
    prefs = _load(owner)
    topic = _new_topic()
    prefs[PREF_KEY] = topic
    _save(owner, prefs)
    return topic


def public_server_url() -> str:
    """The ntfy address phones subscribe to (not the internal Docker one)."""
    url = os.getenv("NTFY_PUBLIC_URL", "").strip()
    if not url:
        try:
            from src.integrations import load_integrations
            active = next((i for i in load_integrations()
                           if i.get("preset") == "ntfy" and i.get("enabled", True) and i.get("base_url")), None)
            url = (active or {}).get("base_url", "")
        except Exception:
            url = ""
    return (url or "http://localhost:8091").rstrip("/")
