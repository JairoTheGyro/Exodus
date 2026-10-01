"""Owned note ingestion shared by post-commit hooks and /api/personal/text."""
import hashlib
import json
import logging
import threading

log = logging.getLogger(__name__)
_condition = threading.Condition()
_pending = set()
_worker = None
_sync_lock = threading.RLock()


def note_text(note):
    items = note.items or []
    if isinstance(items, str):
        try: items = json.loads(items)
        except (ValueError, TypeError): items = []
    lines = [note.title or '', note.content or '']
    if isinstance(items, list):
        lines += [('☑ ' if item.get('done') else '☐ ') + str(item.get('text', ''))
                  for item in items if isinstance(item, dict)]
    return '\n'.join(lines).strip()


def fingerprint(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def note_fingerprint(note):
    text = note_text(note)
    tags = note.tags
    archived = bool(note.archived)
    # Preserve existing fingerprints for ordinary untagged active notes.
    if not tags and not archived:
        return fingerprint(text)
    return fingerprint(json.dumps({'text': text, 'tags': tags, 'is_archived': archived}, sort_keys=True))


def current_metadata(metadata):
    """Fail closed on stale/deleted note hits, even while Chroma is unavailable."""
    if not metadata or metadata.get('kind') != 'note':
        return True
    from core.database import SessionLocal, Note
    from src.home_store import ai_free
    owner = metadata.get('owner')
    if not owner or ai_free(owner):
        return False
    with SessionLocal() as db:
        note = db.query(Note).filter(Note.id == metadata.get('note_id'), Note.owner == owner).first()
        return bool(note and note_fingerprint(note) == metadata.get('note_fingerprint'))


def ingest_note(note_id, owner, *, rag=None, require_existing=False):
    """Index the latest committed note, with stable chunk IDs and owner metadata.

    No loopback HTTP or credentials: the endpoint and save hooks call this same
    routine. A failed index never rolls back a successfully saved note.
    """
    from core.database import SessionLocal, Note
    from src.ai_policy import AI_OWNER, require_ai
    from src.rag_singleton import get_rag_manager
    if not owner:
        return {'status':'skipped', 'reason':'missing_owner'}
    token = AI_OWNER.set(owner)
    try:
        with _sync_lock:
            with SessionLocal() as db:
                note = db.query(Note).filter(Note.id == note_id, Note.owner == owner).first()
                if note is None and require_existing:
                    return {'status':'not_found'}
                text = note_text(note) if note is not None else ''
                title = note.title or 'Note' if note is not None else 'Note'
                tags = note.tags if note is not None else []
                archived = bool(note.archived) if note is not None else False
                revision = note_fingerprint(note) if note is not None else ''
            # Deletions may remove stale indexes even in AI-free mode; they
            # never embed content. Creation/update must pass the AI policy.
            if note is not None:
                require_ai(owner)
            store = rag or get_rag_manager()
            if store is None or not store.healthy:
                return {'status':'unavailable'}
            where = {'$and':[{'owner':owner},{'note_id':note_id},{'kind':'note'}]}
            chunks = store._split_into_chunks(text, chunk_size=500) if text else []
            prefix = 'note_' + fingerprint(owner+'\0'+note_id)[:32]
            ids = [f'{prefix}_{i}' for i in range(len(chunks))]
            for lane in store._lanes:
                existing = lane.collection.get(where=where, include=[])['ids']
                if chunks:
                    metadata = {'kind':'note','note_id':note_id,'owner':owner,
                                'source':f'note:{note_id}', 'filename':title,
                                'note_fingerprint':revision, 'tags':json.dumps(tags),
                                'is_archived':archived}
                    for offset in range(0,len(chunks),32):
                        batch=chunks[offset:offset+32]
                        lane.collection.upsert(ids=ids[offset:offset+32],documents=batch,
                            embeddings=lane.encode(batch),metadatas=[metadata]*len(batch))
                stale = list(set(existing)-set(ids))
                if stale: lane.collection.delete(ids=stale)
            return {'status':'indexed' if chunks else 'removed','indexed_count':len(chunks)}
    except Exception:
        log.warning('Note indexing deferred; note remains saved')
        return {'status':'unavailable'}
    finally:
        AI_OWNER.reset(token)


def enqueue_note(note_id, owner):
    global _worker
    with _condition:
        _pending.add((note_id, owner))
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, name='exodus-note-index',daemon=True)
            _worker.start()
        _condition.notify()


def _run():
    while True:
        with _condition:
            if not _pending:
                _condition.wait(30)
                if not _pending: continue
            jobs=list(_pending);_pending.clear()
        failed=[]
        for note_id, owner in jobs:
            try:
                if ingest_note(note_id, owner).get('status') == 'unavailable':
                    failed.append((note_id, owner))
            except Exception:
                log.warning('Note indexing deferred; worker will retry')
                failed.append((note_id, owner))
        if failed:
            with _condition:
                _pending.update(failed)
                _condition.wait(30)


def install_hooks(factory, note_class):
    from sqlalchemy import event
    if getattr(factory, '_exodus_note_hooks', False): return
    factory._exodus_note_hooks=True
    def collect(session, flush_context, instances):
        jobs=session.info.setdefault('exodus_note_index',set())
        for note in set(session.new)|set(session.dirty)|set(session.deleted):
            if isinstance(note,note_class) and note.id:
                jobs.add((note.id,note.owner))
    def committed(session):
        for note_id, owner in session.info.pop('exodus_note_index',set()):
            try: enqueue_note(note_id,owner)
            except Exception: log.warning('Note saved; indexing could not be queued')
    def rolled_back(session): session.info.pop('exodus_note_index',None)
    event.listen(factory,'before_flush',collect)
    event.listen(factory,'after_commit',committed)
    event.listen(factory,'after_rollback',rolled_back)
