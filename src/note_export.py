"""Local, account-scoped Notes exports. Temporary disk files bound memory use."""
import json
import re
import tempfile
import zipfile
from datetime import date, datetime, timezone

from fastapi.responses import StreamingResponse

from core.database import Note, SessionLocal


class NoteExportResponse(StreamingResponse):
    """Close the temporary file after success, send failure, or disconnect."""
    def __init__(self, file, format):
        self.export_file = file
        size = file.seek(0, 2)
        file.seek(0)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
        super().__init__(
            self._chunks(),
            media_type='application/zip' if format == 'zip' else 'application/json',
            headers={
                'Content-Disposition': f'attachment; filename="exodus-notes-{stamp}.{format}"',
                'Content-Length': str(size),
                'Cache-Control': 'no-store',
                'X-Content-Type-Options': 'nosniff',
            },
        )

    def _chunks(self):
        while chunk := self.export_file.read(64 * 1024):
            yield chunk

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.export_file.close()


def _raw_record(note):
    # Include every physical column, preserving raw JSON text and null values.
    record = {}
    for column in Note.__table__.columns:
        value = getattr(note, column.name)
        record[column.name] = value.isoformat() if isinstance(value, (datetime, date)) else value
    return record


def _category(note):
    # Notes uses tags, not a separate category column. Match its filter semantics.
    if re.search(r'T\d{2}:\d{2}', note.due_date or ''):
        return 'Reminders'
    return next((tag for tag in note.tags if tag != 'reminder'), 'Default')


def _write_json(file, value):
    # Avoid serializing an entire database or archive in memory.
    for part in json.JSONEncoder(ensure_ascii=True).iterencode(value):
        file.write(part.encode('utf-8'))


def _write_markdown(file, note):
    metadata = _raw_record(note)
    content = metadata.pop('content')
    metadata.update(tags=note.tags, category=_category(note))
    # JSON-quoted values are valid YAML, including hostile titles/newlines.
    file.write(b'---\n')
    for key, value in metadata.items():
        file.write(f'{key}: '.encode())
        _write_json(file, value)
        file.write(b'\n')
    file.write(b'---\n\n')
    if content:
        file.write(content.encode('utf-8'))
        file.write(b'\n\n')
    try:
        items = json.loads(note.items) if note.items else []
    except (ValueError, TypeError):
        items = []  # Raw data remains in frontmatter even if legacy JSON is invalid.
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            indent = item.get('indent', 0)
            indent = min(max(indent, 0), 3) if isinstance(indent, int) else 0
            prefix = '    ' * indent
            checked = 'x' if item.get('done') or item.get('checked') else ' '
            text = str(item.get('text') or '').replace('\n', '\n' + prefix + '      ')
            file.write(f'{prefix}- [{checked}] {text}\n'.encode('utf-8'))
    if note.image_url:
        # Preserve the reference without reading arbitrary paths or remote URLs.
        file.write(('\nAttachment reference: ' + note.image_url + '\n').encode('utf-8'))


def build_note_export(owner, format, *, include_archived=False):
    """Build before sending headers; on failure discard the incomplete export.

    Memory is bounded by a small row batch, the largest note, and ZIP's central
    directory (one small entry per note). Content and output stay on disk.
    """
    if format not in ('zip', 'json'):
        raise ValueError('Unsupported Notes export format')
    file = tempfile.TemporaryFile(mode='w+b')
    try:
        with SessionLocal() as db:
            query = db.query(Note)
            if owner is not None:
                query = query.filter(Note.owner == owner)
            if format == 'zip' and not include_archived:
                query = query.filter(Note.archived == False)
            notes = query.order_by(Note.id).yield_per(10)
            if format == 'zip':
                with zipfile.ZipFile(file, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                    for index, note in enumerate(notes, 1):
                        slug = re.sub(r'[^a-zA-Z0-9_-]+', '-', note.title or '').strip('-')[:70] or 'note'
                        # Sequence prevents collisions; no user-controlled path segments.
                        with archive.open(f'{index:06d}-{slug}.md', 'w', force_zip64=True) as entry:
                            _write_markdown(entry, note)
            else:
                file.write(b'{"format":"exodus.notes","version":1,"exported_at":')
                _write_json(file, datetime.now(timezone.utc).isoformat())
                file.write(b',"notes":[')
                for index, note in enumerate(notes):
                    if index:
                        file.write(b',')
                    record = _raw_record(note)
                    record.update(tags=note.tags, category=_category(note), is_archived=bool(note.archived))
                    _write_json(file, record)
                file.write(b']}\n')
        file.seek(0)
        return file
    except BaseException:
        file.close()
        raise
