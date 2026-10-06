"""Private, revision-checked local scratchpads with recoverable note conversion.

The first account owns scratchpad.md at the configured data root. Other accounts
use opaque subdirectories. A lock protects ownership, text and conversion receipts
across threads/processes; plaintext Markdown is the source of truth for the pad.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
import secrets
from pathlib import Path
import tempfile
import uuid

from src.constants import DATA_DIR

MAX_BYTES = 80_000
NOTE_NAMESPACE = uuid.UUID('bcc11b2d-b3b0-49f5-8582-a829702de2b6')


class ScratchpadConflict(Exception):
    def __init__(self, current, message='The scratchpad changed in another window. Your unsaved text has been kept.'):
        self.current = current
        self.message = message


class ScratchpadEmpty(ValueError):
    pass


class ScratchpadDeleted(ValueError):
    pass


def _safe(path):
    if path.is_symlink():
        raise OSError('Scratchpad storage cannot contain symbolic links')
    return path


def _atomic_write(path, data):
    """Never expose a partially written pad or permissively readable temp file."""
    _safe(path)
    fd, tmp = tempfile.mkstemp(prefix='.scratchpad-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _write_json(path, value):
    _atomic_write(path, json.dumps(value, separators=(',', ':')).encode('utf-8'))


def _read_json(path):
    with _safe(path).open('rb') as stream:
        content = stream.read(4097)
    if len(content) > 4096:
        raise OSError('Invalid scratchpad metadata')
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError('Invalid scratchpad metadata')
    return value


def _revision(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class ScratchpadStore:
    def __init__(self, root=None):
        self.root = Path(root or os.getenv('EXODUS_SCRATCHPAD_DIR') or DATA_DIR)

    @contextmanager
    def _owned_path(self, owner):
        _safe(self.root).mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = _safe(self.root / '.scratchpad.lock')
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            identity = hashlib.sha256((owner or '').encode('utf-8')).hexdigest()
            binding = _safe(self.root / '.scratchpad-owner.json')
            if binding.exists():
                primary = _read_json(binding).get('owner_hash')
                if not isinstance(primary, str) or len(primary) != 64:
                    raise ValueError('Invalid scratchpad ownership')
            else:
                # Never reveal an unowned file to the next account that logs in.
                if (self.root / 'scratchpad.md').exists():
                    raise OSError('An existing scratchpad needs an ownership record')
                primary = identity
                _write_json(binding, {'owner_hash': identity})
            directory = self.root
            if primary != identity:
                parent = _safe(self.root / 'scratchpads')
                parent.mkdir(mode=0o700, exist_ok=True)
                directory = _safe(parent / identity)
                directory.mkdir(mode=0o700, exist_ok=True)
            yield _safe(directory / 'scratchpad.md')
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    @staticmethod
    def _read(path):
        if not path.exists():
            text = ''
        else:
            with _safe(path).open('rb') as stream:
                raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise OSError('Scratchpad exceeds the supported size')
            text = raw.decode('utf-8')
        state_path = _safe(path.parent / '.scratchpad-state.json')
        digest = _revision(text)
        state = _read_json(state_path) if state_path.exists() else {}
        revision = state.get('revision', '')
        if state.get('digest') != digest or not isinstance(revision, str) or len(revision) != 64:
            # Recover from a crash between the Markdown and metadata replaces.
            # A fresh token prevents old requests from overwriting changed text.
            state = {'digest': digest, 'revision': secrets.token_hex(32)}
            _write_json(state_path, state)
        return {'text': text, 'revision': state['revision']}

    @staticmethod
    def _save_text(path, text):
        revision = secrets.token_hex(32)
        _atomic_write(path, text.encode('utf-8'))
        _write_json(path.parent / '.scratchpad-state.json', {'digest': _revision(text), 'revision': revision})
        return {'text': text, 'revision': revision}

    def read(self, owner):
        with self._owned_path(owner) as path:
            return self._read(path)

    def write(self, owner, text, revision):
        raw = text.encode('utf-8')
        if len(raw) > MAX_BYTES:
            raise ValueError('Keep the scratchpad below 80 KB')
        with self._owned_path(owner) as path:
            current = self._read(path)
            if current['revision'] != revision:
                raise ScratchpadConflict(current)
            return self._save_text(path, text)

    def to_note(self, owner, revision, request_id, session_factory, note_model):
        request_id = str(uuid.UUID(str(request_id)))
        note_id = str(uuid.uuid5(NOTE_NAMESPACE, json.dumps([owner or '', request_id])))
        with self._owned_path(owner) as path:
            current = self._read(path)
            receipts = _safe(path.parent / '.scratchpad-receipts')
            receipts.mkdir(mode=0o700, exist_ok=True)
            receipt_path = _safe(receipts / (request_id + '.json'))
            receipt = _read_json(receipt_path) if receipt_path.exists() else None
            if receipt and receipt['revision'] != revision:
                raise ScratchpadConflict(current, 'This save request was already used for different text.')
            with session_factory() as db:
                note = db.query(note_model).filter(note_model.id == note_id, note_model.owner == (owner or None)).first()
                replayed = note is not None
                if receipt and receipt.get('completed') and note is not None:
                    return {'id': note_id, **current, 'cleared': False, 'replayed': True}
                if note is None:
                    if receipt and receipt.get('committed'):
                        raise ScratchpadDeleted('The saved note was subsequently deleted; the scratchpad was kept.')
                    if current['revision'] != revision:
                        raise ScratchpadConflict(current)
                    if not current['text'].strip():
                        raise ScratchpadEmpty('Write a note first')
                    # Persist retry identity before committing. A process crash
                    # never clears the text before the note transaction succeeds.
                    receipt = {'revision': revision, 'id': note_id, 'committed': False}
                    _write_json(receipt_path, receipt)
                    first_line = next(line.strip() for line in current['text'].splitlines() if line.strip())
                    note = note_model(id=note_id, owner=owner or None, title=first_line[:100],
                                      content=current['text'], label='quick-capture', note_type='note', source='user')
                    db.add(note)
                    db.commit()  # Existing owned-note indexing/event hooks apply.
                receipt = {'revision': revision, 'id': note_id, 'committed': True}
                _write_json(receipt_path, receipt)
                cleared = current['revision'] == revision
                if cleared:
                    current = self._save_text(path, '')
                receipt['completed'] = True
                _write_json(receipt_path, receipt)
                return {'id': note_id, **current, 'cleared': cleared, 'replayed': replayed}
