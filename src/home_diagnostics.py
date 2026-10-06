"""On-demand local measurements; never infer mail delivery or vault client sync."""
import asyncio
from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

from sqlalchemy import select
from core.database import SessionLocal, Note, CalendarEvent, CalendarCal
from src.constants import DATA_DIR, SCHEDULED_EMAILS_DB
from src.vaultwarden_service import VaultwardenService


def current_rss_bytes():
    """Current resident memory, not resource.getrusage's lifetime high-water mark."""
    if sys.platform.startswith('linux'):
        resident_pages = int(Path('/proc/self/statm').read_text().split()[1])
        return resident_pages * os.sysconf('SC_PAGE_SIZE')
    # BSD/macOS ps reports RSS in KiB. Only our own numeric PID is passed.
    result = subprocess.run(['ps', '-o', 'rss=', '-p', str(os.getpid())],
                            check=True, capture_output=True, text=True, timeout=1)
    return int(result.stdout.strip()) * 1024


def _database_probe(models):
    try:
        with SessionLocal() as db:
            for model in models:
                db.execute(select(model.__mapper__.primary_key[0]).limit(1)).first()
        return {'status': 'ok', 'detail': 'Local database read succeeded.'}
    except Exception:
        # Exceptions can include SQL and credentials; expose neither.
        return {'status': 'unavailable', 'detail': 'The local database could not be read.'}


def _mail_probe():
    path = Path(SCHEDULED_EMAILS_DB)
    if not path.is_file():
        return {'status': 'not_initialized', 'detail': 'Mail cache has not been created yet.'}
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
            for table in ('email_message_index', 'email_body_preview_cache'):
                db.execute('SELECT 1 FROM ' + table + ' LIMIT 1').fetchone()
        return {'status': 'ok', 'detail': 'Local mail cache is readable; this does not check IMAP or SMTP.'}
    except sqlite3.Error:
        return {'status': 'unavailable', 'detail': 'The local mail cache could not be read.'}


def local_measurements():
    try:
        memory = {'status': 'ok', 'rss_bytes': current_rss_bytes(), 'scope': 'Exodus process'}
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        memory = {'status': 'unavailable', 'rss_bytes': None, 'scope': 'Exodus process'}
    root = Path(os.getenv('EXODUS_SCRATCHPAD_DIR') or DATA_DIR)
    try:
        usage = shutil.disk_usage(root)
        disk = {'status': 'ok', 'path': '/data' if str(root) == '/data' else 'Local data directory',
                'total_bytes': usage.total, 'free_bytes': usage.free}
    except OSError:
        disk = {'status': 'unavailable', 'path': 'Local data directory', 'total_bytes': None, 'free_bytes': None}
    return {'memory': memory, 'disk': disk, 'databases': {
        'notes': _database_probe((Note,)), 'calendar': _database_probe((CalendarCal, CalendarEvent)),
        'mail_cache': _mail_probe(),
    }}


async def diagnostics(vault_service=None):
    vault_service = vault_service or VaultwardenService()

    async def vault_check():
        try:
            status = await asyncio.wait_for(vault_service.status(), timeout=3.5)
            return {'status': status['status'], 'detail': status['detail'],
                    'sync_status': status['sync']['status']}
        except Exception:
            return {'status': 'unavailable', 'detail': 'Vaultwarden health is unavailable.', 'sync_status': 'unknown'}

    result, vault = await asyncio.gather(asyncio.to_thread(local_measurements), vault_check())
    result['databases']['vaultwarden'] = vault
    result['checked_at'] = datetime.now(timezone.utc).isoformat()
    return result
