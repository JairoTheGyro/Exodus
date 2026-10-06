"""Vault-domain tool implementations.

Extracted from tool_implementations.py as part of slice 1 (#4082/#4071).
Holds the Bitwarden CLI wrappers (vault_search / vault_get / vault_unlock)
and their helpers (_load_vault_config, _run_bw).
``src.tool_implementations`` re-exports these for backward compatibility.
"""
import json
from typing import Dict, Optional

from src.constants import VAULT_FILE
from src.tools._common import _parse_tool_args


def _load_vault_config(owner=None) -> Dict:
    from src.vault_accounts import load_config
    return load_config(owner)


async def _run_bw(args: list, session=None, input_text=None, owner=None) -> tuple:
    from routes.vault.vault_routes import _run_bw as run
    return await run(args, session=session, input_text=input_text, owner=owner)


async def do_vault_search(content: str, owner: Optional[str] = None) -> Dict:
    """Search the vault by keyword. Returns matching item names + URLs, NO passwords."""
    if not owner or owner in {"api", "internal-tool"}:
        return {"error": "A named Exodus account is required for vault access", "exit_code": 1}
    try:
        args = _parse_tool_args(content)
    except ValueError:
        return {"error": "Invalid JSON arguments", "exit_code": 1}
    query = args.get("query", "").strip()
    if not query:
        return {"error": "query is required", "exit_code": 1}

    cfg = _load_vault_config(owner)
    session = cfg.get("session")
    if not session:
        return {"error": "Vault is locked. Run vault_unlock or provide session key in settings.", "exit_code": 1}

    stdout, stderr, rc = await _run_bw(["list", "items", "--search", query], session=session, owner=owner)
    if rc != 0:
        return {"error": f"bw failed: {stderr[:300]}", "exit_code": 1}

    try:
        items = json.loads(stdout)
    except json.JSONDecodeError:
        return {"error": "Failed to parse bw output", "exit_code": 1}

    if not items:
        return {"output": f"No vault items match '{query}'.", "exit_code": 0}

    lines = [f"Found {len(items)} item(s) matching '{query}':"]
    for it in items[:20]:
        item_id = it.get("id", "?")
        name = it.get("name", "?")
        login = it.get("login") or {}
        username = login.get("username", "")
        uris = login.get("uris") or []
        url = uris[0].get("uri", "") if uris else ""
        parts = [f"[{item_id[:8]}] {name}"]
        if username:
            parts.append(f"user: {username}")
        if url:
            parts.append(f"url: {url}")
        lines.append("- " + " · ".join(parts))
    lines.append("\nUse vault_get(item_id, reason) to retrieve the password.")
    return {"output": "\n".join(lines), "exit_code": 0}


async def do_vault_get(content: str, owner: Optional[str] = None) -> Dict:
    """Retrieve a full vault entry (including password) by item ID. Logs access to assistant chat."""
    if not owner or owner in {"api", "internal-tool"}:
        return {"error": "A named Exodus account is required for vault access", "exit_code": 1}
    try:
        args = _parse_tool_args(content)
    except ValueError:
        return {"error": "Invalid JSON arguments", "exit_code": 1}
    item_id = args.get("item_id", "").strip()
    reason = args.get("reason", "").strip()
    if not item_id:
        return {"error": "item_id is required", "exit_code": 1}
    if not reason:
        return {"error": "reason is required — explain WHY you need this password", "exit_code": 1}

    cfg = _load_vault_config(owner)
    session = cfg.get("session")
    if not session:
        return {"error": "Vault is locked. Unlock first.", "exit_code": 1}

    stdout, stderr, rc = await _run_bw(["get", "item", item_id], session=session, owner=owner)
    if rc != 0:
        return {"error": f"bw failed: {stderr[:300]}", "exit_code": 1}

    try:
        item = json.loads(stdout)
    except json.JSONDecodeError:
        return {"error": "Failed to parse bw output", "exit_code": 1}

    login = item.get("login") or {}
    name = item.get("name", "?")

    # Audit log to assistant chat
    try:
        from src.assistant_log import log_to_assistant
        if owner:
            log_to_assistant(
                owner,
                f"Retrieved password for **{name}** — reason: {reason}",
                category="Vault",
            )
    except Exception:
        pass

    output = [
        f"Vault item: {name}",
        f"Username: {login.get('username', '(none)')}",
        f"Password: {login.get('password', '(none)')}",
    ]
    if login.get("totp"):
        output.append(f"TOTP secret: {login['totp']}")
    uris = login.get("uris") or []
    if uris:
        output.append("URLs: " + ", ".join(u.get("uri", "") for u in uris))
    if item.get("notes"):
        output.append(f"Notes: {item['notes']}")

    return {"output": "\n".join(output), "exit_code": 0}


async def do_vault_unlock(content: str, owner: Optional[str] = None) -> Dict:
    """Unlock the vault using a master password. Stores the resulting session key."""
    if not owner or owner in {"api", "internal-tool"}:
        return {"error": "A named Exodus account is required for vault access", "exit_code": 1}
    try:
        args = _parse_tool_args(content)
    except ValueError:
        return {"error": "Invalid JSON arguments", "exit_code": 1}
    master_password = args.get("master_password", "")
    if not master_password:
        return {"error": "master_password is required", "exit_code": 1}

    # Do not pass the master password as an argv element. Local process lists
    # can expose argv to other users; stdin keeps the secret out of `ps`.
    stdout, stderr, rc = await _run_bw(["unlock", "--raw"], input_text=master_password + "\n", owner=owner)
    if rc != 0:
        return {"error": f"Unlock failed: {stderr[:300]}", "exit_code": 1}

    session = stdout.strip()
    if not session:
        return {"error": "bw returned empty session", "exit_code": 1}

    from src.vault_accounts import load_config, save_config
    from datetime import datetime as _dt
    cfg = load_config(owner)
    cfg["session"] = session
    cfg["unlocked_at"] = _dt.utcnow().isoformat()
    save_config(owner, cfg)
    return {"output": "Your vault is unlocked.", "exit_code": 0}
