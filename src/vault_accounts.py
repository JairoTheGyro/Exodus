"""Owner-scoped optional Bitwarden CLI state, separate from the web vault."""
import hashlib
import json
import os
from pathlib import Path
from core.atomic_io import atomic_write_json
from src.constants import VAULT_FILE


def account_dir(owner):
    if not owner or owner in {'api', 'internal-tool'}:
        raise ValueError('A named Exodus account is required for vault access')
    identity = hashlib.sha256(str(owner).strip().lower().encode()).hexdigest()
    directory = Path(VAULT_FILE).parent / 'vault-accounts' / identity
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory


def load_config(owner):
    try:
        value = json.loads((account_dir(owner) / 'config.json').read_text())
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_config(owner, value):
    path = account_dir(owner) / 'config.json'
    atomic_write_json(str(path), value, indent=2)
    os.chmod(path, 0o600)


def cli_environment(owner):
    environment = dict(os.environ)
    for key in ('BW_SESSION', 'BW_PASSWORD', 'BW_CLIENTID', 'BW_CLIENTSECRET'):
        environment.pop(key, None)
    directory = account_dir(owner) / 'cli'
    directory.mkdir(exist_ok=True, mode=0o700)
    environment['BITWARDENCLI_APPDATA_DIR'] = str(directory)
    return environment
