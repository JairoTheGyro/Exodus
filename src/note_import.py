"""Bounded, local import of Exodus v1 Notes JSON; imported rows are new copies."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
import json
import re
import uuid

from fastapi import HTTPException
from core.database import Note, SessionLocal
from src.upload_handler import extract_internal_upload_ids

MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_IMPORT_NOTES = 5000
MAX_IMPORT_ITEMS = 20000
MAX_JSON_STRUCTURE = 600000
MAX_JSON_DEPTH = 32
_ALLOWED = {column.name for column in Note.__table__.columns} | {'tags', 'category', 'is_archived'}
_COLORS = {'', 'red', 'orange', 'yellow', 'green', 'blue', 'purple'}
_TYPES = {'note', 'checklist', 'todo', 'goal', 'draw'}
_REPEAT = re.compile(r'(none|daily|weekly|monthly|yearly|monthly_nth_weekday|monthly_last_weekday|weekly:[0-6]|monthly:day:([1-9]|[12][0-9]|3[01])|monthly:nth:[1-5]:[0-6]|monthly:last:[0-6])\Z')
_TEXT_TOKEN = re.compile(r'[^\s<>"\']+')
_UPLOAD_PATH = re.compile(r'/api/upload/|/uploads/|odysseus://attachment/', re.I)
_ATTACHMENT_START = re.compile(r'\[Attachment:|<!--\s*pdf(?:_form)?_source\b', re.I)


def _invalid(message):
    raise HTTPException(422, message)


def _text(value, field, *, nullable=True, limit=MAX_IMPORT_BYTES):
    if value is None and nullable:
        return None
    if not isinstance(value, str) or len(value) > limit or '\x00' in value:
        _invalid(f'{field} must be valid text within its size limit.')
    # Reject unpaired surrogates before any transaction/SQLite encode operation.
    try:
        value.encode('utf-8')
    except UnicodeError:
        _invalid(f'{field} contains invalid Unicode.')
    return value


def _boolean(row, field, default=False):
    value = row.get(field, default)
    if value is None and field != 'ai_memory_enabled':
        value = default
    if type(value) is not bool:
        _invalid(f'{field} must be true or false.')
    return value


def _timestamp(value, field):
    if value is None:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    value = _text(value, field, nullable=False, limit=100)
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        _invalid(f'{field} must be an ISO date/time.')
    try:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
    except (ValueError, OverflowError):
        _invalid(f'{field} is outside the supported date range.')


def _date_text(value, field):
    if value in (None, ''):
        return value
    value = _text(value, field, nullable=False, limit=100)
    try:
        if 'T' in value:
            datetime.fromisoformat(value.replace('Z', '+00:00'))
        else:
            date.fromisoformat(value)
    except ValueError:
        _invalid(f'{field} must be an ISO date or date/time.')
    return value


def _inert_text(value, warnings):
    if value is None:
        return None
    count = 0

    def inert_token(match):
        nonlocal count
        token = match.group()
        if _UPLOAD_PATH.search(token):
            count += 1
            return '[attachment not imported]'
        return token

    # Consume each non-whitespace token once instead of rescanning from every
    # https:// prefix. Inert prefixes also handle incomplete/nested reference
    # markup without quadratic backtracking on a large untrusted import.
    cleaned = _TEXT_TOKEN.sub(inert_token, value)
    cleaned, replaced = _ATTACHMENT_START.subn('[attachment not imported]', cleaned)
    count += replaced
    # Verify against the canonical forms used by upload reservation/cleanup.
    # Their potentially unbounded markup prefixes are already made inert above.
    if extract_internal_upload_ids(cleaned):
        _invalid('An attachment reference could not be made inert.')
    if count:
        warnings['attachment_references'] += count
    return cleaned


def _items(value, warnings):
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > 5000:
        _invalid('items must be a checklist with at most 5000 entries.')
    cleaned = []
    for item in value:
        if not isinstance(item, dict):
            _invalid('Every checklist item must be an object.')
        text = _text(item.get('text', ''), 'item text', nullable=False)
        result = {'text': _inert_text(text, warnings)}
        if 'id' in item:
            result['id'] = _text(item['id'], 'item id', nullable=False, limit=100)
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', result['id']):
                _invalid('Checklist item IDs must use letters, numbers, hyphens or underscores.')
        else:
            result['id'] = str(uuid.uuid4())
        for field in ('done', 'checked'):
            if field in item:
                result[field] = _boolean(item, field)
        if not {'done', 'checked'} & item.keys():
            result['done'] = False
        indent = item.get('indent', 0)
        if type(indent) is not int or not 0 <= indent <= 3:
            _invalid('Checklist indentation must be 0–3.')
        if 'indent' in item:
            result['indent'] = indent
        if 'due' in item:
            result['due'] = _date_text(item['due'], 'item due date')
        if item.keys() - {'id', 'text', 'done', 'checked', 'indent', 'due'}:
            warnings['item_metadata'] += 1
        cleaned.append(result)
    return json.dumps(cleaned, ensure_ascii=False)


def _row(row, warnings):
    if not isinstance(row, dict) or row.keys() - _ALLOWED:
        _invalid('Each note must be an object containing supported version-1 fields.')
    for field in ('id', 'owner', 'source', 'session_id', 'agent_session_id',
                  'ai_classification', 'ai_content_hash', 'category', 'image_url'):
        if field in row:
            _text(row[field], field)
    note_type = row.get('note_type', 'note')
    if note_type is None: note_type = 'note'
    if not isinstance(note_type, str) or note_type not in _TYPES:
        _invalid('Unsupported note_type.')
    archive = _boolean(row, 'archived', row.get('is_archived', False))
    if 'is_archived' in row and archive != _boolean(row, 'is_archived'):
        _invalid('archived and is_archived must agree.')
    tags = row.get('tags')
    if tags is None:
        label = _text(row.get('label'), 'label') or ''
        tags = label.split()
    if not isinstance(tags, list) or len(tags) > 50:
        _invalid('tags must contain at most 50 text tags.')
    normalized = []
    for value in tags:
        tag = _text(value, 'tag', nullable=False, limit=101).strip().lstrip('#')
        if _inert_text(tag, warnings) != tag:
            continue
        if not tag or len(tag) > 100 or any(c.isspace() for c in tag):
            _invalid('Tags must be nonempty single words, at most 100 characters.')
        if tag not in normalized:
            normalized.append(tag)
    color = _text(row.get('color'), 'color')
    if color and color not in _COLORS:
        color = None
        warnings['backgrounds'] += 1
    if row.get('image_url'):
        warnings['images'] += 1
    if any(row.get(k) for k in ('session_id', 'agent_session_id', 'ai_classification', 'ai_content_hash')):
        warnings['automation_links'] += 1
    if 'ai_memory_enabled' not in row:
        warnings['missing_memory_consent'] += 1
    repeat = row.get('repeat', 'none')
    if repeat in (None, ''): repeat = 'none'
    if not isinstance(repeat, str) or not _REPEAT.fullmatch(repeat):
        _invalid('Unsupported reminder repeat value.')
    order = row.get('sort_order', 0)
    if order is None: order = 0
    if type(order) is not int or not -(2**31) <= order < 2**31:
        _invalid('sort_order must be an integer within range.')
    due = _date_text(row.get('due_date'), 'due_date')
    if due and 'T' in due and not archive:
        warnings['reminders'] += 1
    return dict(
        title=_inert_text(_text('' if row.get('title') is None else row['title'], 'title', nullable=False), warnings),
        content=_inert_text(_text(row.get('content'), 'content'), warnings),
        items=_items(row.get('items'), warnings), note_type=note_type,
        color=color, label=' '.join(normalized) or None, pinned=_boolean(row, 'pinned'),
        archived=archive, ai_memory_enabled=_boolean(row, 'ai_memory_enabled', False),
        due_date=due, repeat=repeat, sort_order=order, source='import',
        session_id=None, agent_session_id=None, ai_classification=None,
        ai_content_hash=None, image_url=None,
        created_at=_timestamp(row.get('created_at'), 'created_at'),
        updated_at=_timestamp(row.get('updated_at'), 'updated_at'),
    )


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _invalid('Duplicate JSON fields are not allowed.')
        result[key] = value
    return result


def _bounded_json_loads(text, budget):
    # Bound container/separator complexity before JSON constructs Python lists
    # and dicts. A small-byte file can otherwise contain millions of tiny items.
    quoted = escaped = False
    depth = 0
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char in '{}[]:,':
            budget['structure'] += 1
            if budget['structure'] > MAX_JSON_STRUCTURE:
                raise HTTPException(413, 'This backup has too many JSON values; split it into smaller files.')
            if char in '{[':
                depth += 1
                if depth > MAX_JSON_DEPTH:
                    _invalid('JSON nesting is too deep.')
            elif char in '}]':
                depth -= 1

    def object_hook(pairs):
        budget['objects'] += 1
        if budget['objects'] > MAX_IMPORT_NOTES + MAX_IMPORT_ITEMS + 1:
            raise HTTPException(413, 'This backup contains too many note/checklist objects.')
        return _unique_object(pairs)

    return json.loads(text, object_pairs_hook=object_hook,
                      parse_constant=lambda _: _invalid('Invalid JSON number.'))


def _prepare_checklists(notes, budget):
    # Count every checklist in the entire file before normalization, UUID
    # creation or ORM allocation. Parse string-encoded v1 lists only once.
    remaining = MAX_IMPORT_ITEMS
    prepared = []
    for index, row in enumerate(notes, 1):
        if not isinstance(row, dict):
            _invalid(f'Note {index}: Each note must be an object.')
        items = row.get('items')
        if isinstance(items, str):
            try:
                items = _bounded_json_loads(items, budget)
            except (ValueError, RecursionError):
                _invalid(f'Note {index}: items must contain a valid JSON checklist.')
        if items is not None:
            if not isinstance(items, list) or len(items) > 5000:
                _invalid(f'Note {index}: items must be a checklist with at most 5000 entries.')
            remaining -= len(items)
            if remaining < 0:
                raise HTTPException(413, 'Import at most 20,000 checklist items across the entire file.')
        prepared.append({**row, 'items': items})
    return prepared


def validate_import(payload):
    if len(payload) > MAX_IMPORT_BYTES:
        raise HTTPException(413, 'Notes imports are limited to 10 MiB.')
    budget = {'structure': 0, 'objects': 0}
    try:
        data = _bounded_json_loads(payload.decode('utf-8-sig'), budget)
    except (ValueError, UnicodeError, RecursionError):
        _invalid('Choose a valid Exodus Notes JSON backup.')
    if (not isinstance(data, dict) or data.get('format') != 'exodus.notes'
            or type(data.get('version')) is not int or data['version'] != 1
            or data.keys() - {'format', 'version', 'exported_at', 'notes'}):
        _invalid('This file is not an Exodus Notes version-1 JSON backup.')
    if 'exported_at' in data:
        _timestamp(data['exported_at'], 'exported_at')
    notes = data.get('notes')
    if not isinstance(notes, list):
        _invalid('The backup must contain a notes array.')
    if len(notes) > MAX_IMPORT_NOTES:
        raise HTTPException(413, 'Import at most 5000 notes at a time.')
    notes = _prepare_checklists(notes, budget)
    warnings = Counter()
    records = []
    for index, row in enumerate(notes, 1):
        try:
            records.append(_row(row, warnings))
        except HTTPException as exc:
            raise HTTPException(exc.status_code, f'Note {index}: {exc.detail}') from None
    return records, warnings


def import_note_json(payload, owner):
    records, warnings = validate_import(payload)
    # Regular ORM writes preserve the shared post-commit index/event hooks.
    # No source IDs, foreign owners or sessions are reused; imports never update.
    with SessionLocal() as db:
        with db.begin():
            for record in records:
                db.add(Note(id=str(uuid.uuid4()), owner=owner, **record))
    labels = {
        'attachment_references': 'Attachment references were replaced with inert text; upload files separately.',
        'images': 'Image attachments were omitted; JSON backups do not contain their files.',
        'backgrounds': 'Custom image backgrounds were omitted.',
        'automation_links': 'Chat, agent and AI classification links were removed.',
        'item_metadata': 'Unsupported checklist metadata was omitted; item text and completion were kept.',
        'missing_memory_consent': 'Older notes without a memory preference were excluded from AI memory by default.',
        'reminders': 'Timed reminders were restored and follow your existing reminder settings.',
    }
    return {'imported': len(records), 'archived': sum(r['archived'] for r in records),
            'warnings': [{'code': key, 'count': count, 'message': labels[key]}
                         for key, count in sorted(warnings.items())]}


async def read_import_body(request):
    length = request.headers.get('content-length')
    if length:
        try:
            if int(length) > MAX_IMPORT_BYTES:
                raise HTTPException(413, 'Notes imports are limited to 10 MiB.')
        except ValueError:
            _invalid('Invalid content length.')
    if request.headers.get('content-encoding', 'identity').lower() != 'identity':
        _invalid('Send an uncompressed JSON backup.')
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_IMPORT_BYTES:
            raise HTTPException(413, 'Notes imports are limited to 10 MiB.')
        body.extend(chunk)
    return body
