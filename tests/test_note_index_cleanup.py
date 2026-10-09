"""Consent/deletion cleanup uses owned metadata, never an embedding initializer."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class Collection:
    def __init__(self, name):
        self.name = name
        self.rows = {
            'owned': {'owner': 'alice', 'note_id': 'n1', 'kind': 'note'},
            'foreign': {'owner': 'bob', 'note_id': 'n1', 'kind': 'note'},
            'other-note': {'owner': 'alice', 'note_id': 'n2', 'kind': 'note'},
            'other-kind': {'owner': 'alice', 'note_id': 'n1', 'kind': 'document'},
        }
        self.upserts = []

    def get(self, *, where, include):
        assert include == []
        clauses = where['$and']
        assert {key for clause in clauses for key in clause} == {'owner', 'note_id', 'kind'}
        return {'ids': [key for key, metadata in self.rows.items()
                        if all(metadata.get(k) == v for clause in clauses for k, v in clause.items())]}

    def delete(self, *, ids):
        for key in ids:
            del self.rows[key]

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)


class Chroma:
    def __init__(self):
        self.collections = {name: Collection(name) for name in (
            'odysseus_rag', 'odysseus_rag_fastembed', 'odysseus_rag_custom',
            'practice-knowledge', 'unrelated-memory')}
        self.opened = []

    def list_collections(self):
        # Support Chroma versions returning lightweight collection objects.
        return [SimpleNamespace(name=name) for name in self.collections]

    def get_collection(self, name, *, embedding_function):
        assert embedding_function is None
        self.opened.append(name)
        return self.collections[name]


@pytest.fixture
def state(monkeypatch, tmp_path):
    from core import database
    from src import note_indexing as ni
    engine = create_engine('sqlite:///' + str(tmp_path / 'notes.db'))
    database.Note.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(database, 'SessionLocal', factory)
    queued = Mock()
    monkeypatch.setattr(ni, 'enqueue_note', queued)
    ni.install_hooks(factory, database.Note)
    monkeypatch.setenv('CHROMA_COLLECTION', 'practice-knowledge')
    mode = {'ai_free': True, 'archive': False}
    monkeypatch.setattr('src.home_store.ai_free', lambda owner: mode['ai_free'])
    monkeypatch.setattr('src.ai_policy.ai_free', lambda owner: mode['ai_free'])
    monkeypatch.setattr('src.home_store.profile', lambda owner: {'ai_include_archived_notes': mode['archive']})
    initializer = Mock(side_effect=AssertionError('Must not initialize embeddings for cleanup'))
    monkeypatch.setattr('src.rag_singleton.get_rag_manager', initializer)
    chroma = Chroma()
    connection = Mock(return_value=chroma)
    monkeypatch.setattr('src.chroma_client.get_chroma_client', connection)

    def write(*, present=True, enabled=True, archived=False, content='Practice avocados'):
        with factory() as db:
            note = db.get(database.Note, 'n1')
            if not present:
                if note is not None:
                    db.delete(note)
            else:
                if note is None:
                    note = database.Note(id='n1', owner='alice', title='Practice')
                    db.add(note)
                note.content = content
                note.ai_memory_enabled = enabled
                note.archived = archived
            db.commit()
    yield SimpleNamespace(ni=ni, factory=factory, write=write, mode=mode, chroma=chroma,
                          initializer=initializer, connection=connection, queued=queued)
    engine.dispose()


@pytest.mark.parametrize('change', ['delete', 'revoke', 'archive'])
def test_ai_free_cleanup_removes_all_owned_lanes_without_models(state, change):
    state.write(present=change != 'delete', enabled=change != 'revoke', archived=change == 'archive')
    result = state.ni.ingest_note('n1', 'alice')
    assert result == {'status': 'removed', 'indexed_count': 0, 'removed_count': 4}
    assert set(state.chroma.opened) == {'odysseus_rag', 'odysseus_rag_custom', 'odysseus_rag_fastembed', 'practice-knowledge'}
    for name, collection in state.chroma.collections.items():
        assert set(collection.rows) == ({'owned', 'foreign', 'other-note', 'other-kind'}
                                        if name == 'unrelated-memory' else {'foreign', 'other-note', 'other-kind'})
    state.initializer.assert_not_called()


def test_permitted_ai_free_save_does_not_connect_to_vector_service(state):
    state.write()
    assert state.ni.ingest_note('n1', 'alice') == {'status': 'skipped', 'reason': 'ai_free'}
    state.connection.assert_not_called()
    state.initializer.assert_not_called()


def test_full_mode_revocation_also_avoids_model_initialization(state):
    state.mode['ai_free'] = False
    state.write(enabled=False)
    assert state.ni.ingest_note('n1', 'alice')['status'] == 'removed'
    state.initializer.assert_not_called()


def test_missing_explicit_or_foreign_note_does_not_open_chroma(state):
    state.write()
    assert state.ni.ingest_note('n1', 'bob', require_existing=True)['status'] == 'not_found'
    assert state.ni.ingest_note('absent', 'alice', require_existing=True)['status'] == 'not_found'
    state.connection.assert_not_called()


def test_offline_cleanup_is_retryable_and_preserves_rows_until_recovery(state):
    state.write(enabled=False)
    state.connection.side_effect = RuntimeError('offline')
    assert state.ni.ingest_note('n1', 'alice')['status'] == 'unavailable'
    assert all('owned' in c.rows for c in state.chroma.collections.values())
    state.connection.side_effect = None
    assert state.ni.ingest_note('n1', 'alice')['status'] == 'removed'
    state.initializer.assert_not_called()


def test_no_existing_collections_does_not_create_any(state):
    state.write(enabled=False)
    state.chroma.collections = {}
    assert state.ni.ingest_note('n1', 'alice')['status'] == 'removed'
    assert state.chroma.opened == []


def test_partial_failure_is_not_reported_as_success_and_retry_finishes(state):
    state.write(enabled=False)
    collection = state.chroma.collections['practice-knowledge']
    delete = collection.delete
    collection.delete = Mock(side_effect=RuntimeError('unavailable'))
    assert state.ni.ingest_note('n1', 'alice')['status'] == 'unavailable'
    assert 'owned' in collection.rows
    collection.delete = delete
    assert state.ni.ingest_note('n1', 'alice')['status'] == 'removed'
    assert 'owned' not in collection.rows


@pytest.mark.parametrize('change', ['delete', 'revoke', 'ai_free', 'edit'])
def test_live_change_during_encode_prevents_upsert(state, change):
    state.mode['ai_free'] = False
    state.write()
    collection = state.chroma.collections['practice-knowledge']
    def encode(batch):
        if change == 'delete': state.write(present=False)
        elif change == 'revoke': state.write(enabled=False)
        elif change == 'edit': state.write(content='Changed during encode')
        else: state.mode['ai_free'] = True
        return [[1., 2.] for _ in batch]
    lane = SimpleNamespace(collection=collection, encode=encode)
    rag = SimpleNamespace(healthy=True, _lanes=[lane], _split_into_chunks=lambda text, **kw: [text])
    result = state.ni.ingest_note('n1', 'alice', rag=rag)
    assert result['status'] == {'delete': 'removed', 'revoke': 'removed', 'ai_free': 'skipped', 'edit': 'unavailable'}[change]
    assert collection.upserts == []
    assert 'foreign' in collection.rows


def test_revocation_before_encode_never_calls_encoder(state):
    state.mode['ai_free'] = False
    state.write()
    collection = state.chroma.collections['practice-knowledge']
    encode = Mock(side_effect=AssertionError('Consent revoked before encode'))
    def split(text, **kwargs):
        state.write(enabled=False)
        return [text]
    rag = SimpleNamespace(healthy=True, _lanes=[SimpleNamespace(collection=collection, encode=encode)],
                          _split_into_chunks=split)
    assert state.ni.ingest_note('n1', 'alice', rag=rag)['status'] == 'removed'
    encode.assert_not_called()


def test_ai_free_account_requeue_selects_cleanup_not_permitted_notes(state):
    from core.database import Note
    state.write(archived=True)
    with state.factory() as db:
        db.add_all([Note(id='active', owner='alice', title='Allowed'),
                    Note(id='revoked', owner='alice', ai_memory_enabled=False),
                    Note(id='foreign', owner='bob', ai_memory_enabled=False)])
        db.commit()
    state.queued.reset_mock()
    state.ni.reindex_owner_notes('alice')
    assert {call.args for call in state.queued.call_args_list} == {('n1', 'alice'), ('revoked', 'alice')}
    state.connection.assert_not_called()


def test_injected_unhealthy_embeddings_can_still_delete(state):
    state.write(enabled=False)
    collection = state.chroma.collections['practice-knowledge']
    rag = SimpleNamespace(healthy=False, _collections_for_delete=lambda: [('existing', collection)])
    assert state.ni.ingest_note('n1', 'alice', rag=rag)['status'] == 'removed'
    assert 'owned' not in collection.rows
    state.connection.assert_not_called()
