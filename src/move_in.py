"""Exodus "Move to Exodus": bring in data exported from Google, Apple and Microsoft.

One upload at a time: a ZIP (a Google Takeout part, an iCloud or OneDrive
download, any ZIP) or a single .ics / .vcf / .json file. ``scan`` lists what
it found; ``run_import`` brings in what the person ticks, reusing Exodus's own
importers:

- calendars (.ics)          -> routes.calendar_routes.import_ics_content
- contacts (.vcf, contacts .csv; admin only, the address book is shared)
                            -> routes.contacts.contacts_routes import helpers
- Google Keep notes (.json) -> converted to an Exodus Notes backup, then
                               src.note_import.import_note_json (all its checks)
- files (PDF, text, CSV, pictures) -> Library → Files, like an upload
- mail (.mbox) is not imported: connect the account in Email settings.

Safety: ZIPs are never unpacked to disk. Each part is read in memory with a
size limit; parts with suspicious compression, odd paths or too many entries
are skipped and reported.
"""
from __future__ import annotations

import io
import json
import os
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Iterator, Optional

MAX_ENTRIES = 50000
MAX_PART_BYTES = 25 * 1024 * 1024        # any single calendar/contacts/file part
MAX_KEEP_NOTE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED = 8 * 1024 ** 3   # stop reading a ZIP past this
MAX_RATIO = 200                          # zip-bomb guard (uncompressed / compressed)
MAX_KEEP_NOTES = 5000

FILE_FORMATS = {'.pdf', '.txt', '.md', '.csv', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp',
                '.tif', '.tiff', '.svg', '.avif', '.ico'}
OFFICE = {'.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt', '.odt', '.ods', '.odp', '.pages', '.numbers', '.key'}
PHOTO_DIRS = ('google photos/', 'photos/', 'icloud photos/')
KEEP_COLORS = {'RED': 'red', 'ORANGE': 'orange', 'YELLOW': 'yellow', 'GREEN': 'green', 'TEAL': 'green',
               'BLUE': 'blue', 'CERULEAN': 'blue', 'PURPLE': 'purple', 'PINK': 'red', 'BROWN': 'orange'}


@dataclass
class Part:
    kind: str           # calendar | contacts | keep | file | mail | photo | office | skipped
    name: str           # path inside the export (display only)
    size: int
    reason: str = ''


@dataclass
class Scan:
    parts: list[Part] = field(default_factory=list)

    def summary(self) -> dict:
        def of(kind):
            return [p for p in self.parts if p.kind == kind]
        return {
            'calendars': [p.name for p in of('calendar')],
            'contacts': len(of('contacts')),
            'keep_notes': len(of('keep')),
            'files': len(of('file')),
            'files_bytes': sum(p.size for p in of('file')),
            'mail': len(of('mail')),
            'photos': len(of('photo')),
            'office': len(of('office')),
            'skipped': [{'name': p.name, 'reason': p.reason} for p in of('skipped')][:50],
        }


def _safe_name(name: str) -> Optional[str]:
    """A display path inside the export, or None for odd/unsafe names."""
    if not name or '\x00' in name or name.startswith('/') or '\\' in name:
        return None
    parts = PurePosixPath(name).parts
    if any(p in ('..', '') for p in parts) or len(name) > 400:
        return None
    return name


def classify(name: str, size: int) -> Part:
    lower = name.lower()
    suffix = PurePosixPath(lower).suffix
    base = PurePosixPath(lower).name
    if size > MAX_PART_BYTES and suffix != '.mbox':
        return Part('skipped', name, size, 'too large')
    if suffix in ('.ics', '.ical', '.ifb'):
        return Part('calendar', name, size)
    if suffix == '.vcf' or (suffix == '.csv' and 'contact' in lower):
        return Part('contacts', name, size)
    if '/keep/' in f'/{lower}':
        if suffix == '.json' and size <= MAX_KEEP_NOTE_BYTES:
            return Part('keep', name, size)
        return Part('skipped', name, size, 'Keep extra (labels list or a picture on a note)')
    if suffix == '.mbox':
        return Part('mail', name, size)
    if any(f'/{d}' in f'/{lower}' for d in PHOTO_DIRS):
        return Part('photo', name, size)
    if suffix in OFFICE:
        return Part('office', name, size)
    if suffix in FILE_FORMATS and not base.startswith('.') and not lower.startswith('__macosx/'):
        return Part('file', name, size)
    return Part('skipped', name, size, 'not a supported kind of file')


def _zip_entries(zf: zipfile.ZipFile) -> Iterator[tuple[zipfile.ZipInfo, Optional[str], str]]:
    total = 0
    for index, info in enumerate(zf.infolist()):
        if index >= MAX_ENTRIES:
            yield info, None, 'too many files in this export'
            return
        if info.is_dir():
            continue
        name = _safe_name(info.filename)
        if name is None:
            yield info, None, 'unusual file path'
            continue
        if info.flag_bits & 0x1:
            yield info, None, 'password-protected'
            continue
        total += info.file_size
        if total > MAX_TOTAL_UNCOMPRESSED:
            yield info, None, 'export too large; split it into smaller parts'
            return
        if info.compress_size and info.file_size / max(info.compress_size, 1) > MAX_RATIO and info.file_size > 1024 * 1024:
            yield info, None, 'suspicious compression'
            continue
        yield info, name, ''


def scan(path: str, filename: str = '') -> Scan:
    """List what an uploaded export contains (reads names and sizes only)."""
    result = Scan()
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            for info, name, problem in _zip_entries(zf):
                if problem:
                    result.parts.append(Part('skipped', _safe_name(info.filename) or '(unnamed)', info.file_size, problem))
                    continue
                part = classify(name, info.file_size)
                if part.kind == 'keep' and not _looks_like_keep(_read_zip(zf, info, MAX_KEEP_NOTE_BYTES)):
                    part = Part('skipped', name, info.file_size, 'not a Google Keep note')
                result.parts.append(part)
    else:
        name = os.path.basename(filename or 'upload') or 'upload'
        part = classify(name, os.path.getsize(path))
        if part.kind not in ('calendar', 'contacts'):
            part = Part('skipped', name, part.size, 'upload a ZIP export, or a single .ics or .vcf file')
        result.parts.append(part)
    return result


def _read_zip(zf: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    with zf.open(info) as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError('part larger than its limit')
    return data


def _looks_like_keep(raw: bytes) -> bool:
    try:
        data = json.loads(raw.decode('utf-8-sig'))
    except (ValueError, UnicodeError):
        return False
    return isinstance(data, dict) and ('textContent' in data or 'listContent' in data) and 'title' in data


def keep_to_exodus(raw_notes: list[dict]) -> bytes:
    """Convert Google Keep notes to an Exodus Notes version-1 backup."""
    notes = []
    for keep in raw_notes[:MAX_KEEP_NOTES]:
        if keep.get('isTrashed'):
            continue
        items = None
        if isinstance(keep.get('listContent'), list):
            items = [{'text': str(i.get('text', ''))[:2000], 'done': bool(i.get('isChecked'))}
                     for i in keep['listContent'] if isinstance(i, dict)][:5000]
        labels = []
        for label in keep.get('labels') or []:
            name = str((label or {}).get('name', '')).strip()
            tag = re.sub(r'\s+', '-', name)[:100]
            if tag and tag not in labels:
                labels.append(tag)
        note = {
            'title': str(keep.get('title', ''))[:500],
            'content': None if items is not None else str(keep.get('textContent', '')),
            'items': items,
            'note_type': 'checklist' if items is not None else 'note',
            'color': KEEP_COLORS.get(str(keep.get('color', '')).upper(), ''),
            'pinned': bool(keep.get('isPinned')),
            'archived': bool(keep.get('isArchived')),
            'tags': labels[:50],
            'ai_memory_enabled': False,  # imported notes opt in to AI memory later
        }
        notes.append(note)
    return json.dumps({'format': 'exodus.notes', 'version': 1, 'notes': notes}).encode('utf-8')


def run_import(path: str, filename: str, owner: Optional[str], *, choose: dict, is_admin: bool) -> dict:
    """Import the chosen kinds. Returns counts and plain-language notes."""
    from core.database import SessionLocal
    report = {'calendars': [], 'contacts': None, 'notes': None, 'files': {'imported': 0, 'skipped': []},
              'messages': []}

    def parts_with_data():
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as zf:
                for info, name, problem in _zip_entries(zf):
                    if problem:
                        continue
                    part = classify(name, info.file_size)
                    if part.kind in ('calendar', 'contacts', 'keep', 'file') and choose.get(part.kind):
                        try:
                            yield part, _read_zip(zf, info, MAX_PART_BYTES)
                        except ValueError:
                            continue
        else:
            part = classify(os.path.basename(filename or 'upload'), os.path.getsize(path))
            if part.kind in ('calendar', 'contacts') and choose.get(part.kind):
                with open(path, 'rb') as handle:
                    yield part, handle.read(MAX_PART_BYTES + 1)[:MAX_PART_BYTES]

    keep_notes = []
    vcards, contact_csvs = [], []
    for part, data in parts_with_data():
        if part.kind == 'calendar':
            report['calendars'].append(_import_calendar(SessionLocal, owner, part.name, data))
        elif part.kind == 'contacts':
            (contact_csvs if part.name.lower().endswith('.csv') else vcards).append(data)
        elif part.kind == 'keep':
            try:
                keep_notes.append(json.loads(data.decode('utf-8-sig')))
            except (ValueError, UnicodeError):
                continue
        elif part.kind == 'file':
            outcome = _import_file(owner, part.name, data)
            if outcome is True:
                report['files']['imported'] += 1
            else:
                report['files']['skipped'].append({'name': part.name, 'reason': outcome})

    if vcards or contact_csvs:
        if not is_admin:
            report['messages'].append('Contacts are shared in Exodus and only the admin can import them.')
        else:
            report['contacts'] = _import_contacts(vcards, contact_csvs)
    if keep_notes:
        from src.note_import import import_note_json
        report['notes'] = import_note_json(keep_to_exodus(keep_notes), owner)
    return report


def _import_calendar(session_factory, owner, name, data) -> dict:
    from icalendar import Calendar as iCal
    from routes.calendar_routes import import_ics_content, FALLBACK_OWNER
    label = PurePosixPath(name).name
    try:
        cal_data = iCal.from_ical(data)
    except Exception:
        return {'file': label, 'error': 'not a valid calendar file'}
    db = session_factory()
    try:
        result = import_ics_content(db, owner or FALLBACK_OWNER, cal_data, '', label)
        return {'file': label, 'calendar': result['calendar'], 'imported': result['imported'], 'skipped': result['skipped']}
    except Exception:
        db.rollback()
        return {'file': label, 'error': 'could not be imported'}
    finally:
        db.close()


def _import_contacts(vcards: list[bytes], csvs: list[bytes]) -> dict:
    from routes.contacts.contacts_routes import _import_csv_contacts, _import_vcards
    totals = {'imported': 0}
    for blob in vcards:
        result = _import_vcards(blob.decode('utf-8', errors='replace')) or {}
        totals['imported'] += int(result.get('imported') or 0)
    for blob in csvs:
        result = _import_csv_contacts(blob.decode('utf-8-sig', errors='replace')) or {}
        totals['imported'] += int(result.get('imported') or 0)
    return totals


def _import_file(owner, name, data):
    """Save one file into Library → Files. True, or a reason it was skipped."""
    from core.database import DocumentFile, SessionLocal
    from routes.local_document_routes import FORMATS, _path
    from src.upload_limits import DOCUMENT_UPLOAD_MAX_BYTES
    from src.upload_handler import secure_filename
    filename = secure_filename(PurePosixPath(name).name)
    extension = PurePosixPath(filename).suffix.lower()
    if extension not in FORMATS:
        return 'not a supported kind of file'
    if not data:
        return 'empty file'
    if len(data) > DOCUMENT_UPLOAD_MAX_BYTES:
        return 'too large'
    if len(filename) > 160:
        filename = filename[:160 - len(extension)].rstrip('.') + extension
    file_id = uuid.uuid4().hex
    path = _path(f'{file_id}-{filename}')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
        with SessionLocal() as db:
            db.add(DocumentFile(id=file_id, owner=owner, filename=filename, storage_name=path.name,
                                file_size=len(data), mime_type=FORMATS[extension]))
            db.commit()
        return True
    except Exception:
        path.unlink(missing_ok=True)
        return 'could not be saved'
