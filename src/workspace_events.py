"""Small, owner-scoped UI invalidation bus for this single-worker workspace.

No content, credentials, row IDs or owner names are sent to browsers. Events are
hints to reread existing permission-checked APIs, not a durable change log. A new
SSE connection always invalidates the view, recovering missed/restarted events.
The automation event bus in src.event_bus has a separate purpose and is untouched.
"""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass

TOPICS = frozenset({'notes', 'documents', 'calendar', 'inbox', 'profile', 'goals',
                    'focus', 'team', 'scratchpad'})
_lock = threading.RLock()
_subscribers: set['Subscription'] = set()


@dataclass(eq=False)
class Subscription:
    owners: frozenset[str]
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue
    closed: bool = False

    def close(self):
        with _lock:
            self.closed = True
            _subscribers.discard(self)


def subscribe_workspace_events(owners):
    """Called in the async request loop; only trusted route code selects owners."""
    sub = Subscription(frozenset(str(owner or '') for owner in owners),
                       asyncio.get_running_loop(), asyncio.Queue(maxsize=64))
    with _lock:
        _subscribers.add(sub)
    return sub


def _deliver(sub, topic):
    if sub.closed:
        return
    if sub.queue.full():
        # Slow tabs need one full refresh, not unbounded retained events.
        while not sub.queue.empty():
            sub.queue.get_nowait()
        sub.queue.put_nowait('reconnect')
    else:
        sub.queue.put_nowait(topic)


def publish_workspace_event(owner, topic):
    """Nonblocking, best-effort invalidation AFTER a successful durable write."""
    if topic not in TOPICS:
        raise ValueError('Unknown workspace event topic')
    owner = str(owner or '')
    with _lock:
        targets = [sub for sub in _subscribers if owner in sub.owners and not sub.closed]
    for sub in targets:
        try:
            sub.loop.call_soon_threadsafe(_deliver, sub, topic)
        except RuntimeError:  # The browser/server loop closed during publication.
            sub.close()


def install_database_hooks(factory, models, calendar_event, calendar_class):
    """Notify once per owner/topic after commit, including tool and bulk writes.

    Pending hints belong to their SQLAlchemy transaction. Savepoint rollback
    discards only that savepoint; outer rollback discards everything. Writes
    never fail because a browser is absent or has disconnected.
    """
    from sqlalchemy import and_, event, inspect, or_, select
    if getattr(factory, '_exodus_workspace_hooks', False):
        return
    factory._exodus_workspace_hooks = True
    key = 'exodus_workspace_events'

    def remember(session, owner, topic):
        tx = session.get_nested_transaction() or session.get_transaction()
        if tx is not None:
            session.info.setdefault(key, {}).setdefault(tx, set()).add((owner, topic))

    def collect(session, flush_context, instances):
        for row in set(session.new) | set(session.dirty) | set(session.deleted):
            model = type(row)
            if model not in models and model is not calendar_event:
                continue
            if row in session.dirty and not session.is_modified(row, include_collections=False):
                continue
            if model is calendar_event:
                # Include both owners when a row moves between calendars.
                calendar_ids = {row.calendar_id}
                calendar_ids.update(inspect(row).attrs.calendar_id.history.deleted)
                calendar = row.calendar
                if calendar is not None:
                    remember(session, calendar.owner, 'calendar')
                for calendar_id in calendar_ids - {None}:
                    cal = session.get(calendar_class, calendar_id)
                    if cal is not None:
                        remember(session, cal.owner, 'calendar')
            else:
                remember(session, row.owner, models[model])
                for previous_owner in inspect(row).attrs.owner.history.deleted:
                    remember(session, previous_owner, models[model])

    def bulk(orm_state):
        if not (orm_state.is_update or orm_state.is_delete):
            return
        mapper = orm_state.bind_arguments.get('mapper')
        model = mapper.class_ if mapper is not None else None
        if model not in models and model is not calendar_event:
            return
        statement = orm_state.statement
        if model is calendar_event:
            query = select(calendar_class.owner).join(
                calendar_event, calendar_event.calendar_id == calendar_class.id)
            topic = 'calendar'
        else:
            query = select(model.owner)
            topic = models[model]
        query = query.where(*statement._where_criteria).distinct()
        parameters = orm_state.parameters
        if isinstance(parameters, list):
            # SQLAlchemy's executemany UPDATE-by-primary-key has no WHERE on
            # its template statement. Restrict the lookup to those real rows.
            keys = [column.key for column in mapper.primary_key]
            targets = [and_(*(getattr(model, key) == values[key] for key in keys))
                       for values in parameters if all(key in values for key in keys)]
            if not targets:
                return
            query = query.where(or_(*targets))
            parameters = None
        # Preserve explicit bind parameters used by scoped bulk update/delete.
        # This is a local owner-only SELECT, never a content fetch or network call.
        for owner in orm_state.session.execute(query, parameters).scalars():
            remember(orm_state.session, owner, topic)

    def committed(session):
        tx = session.get_nested_transaction() or session.get_transaction()
        pending = session.info.get(key, {})
        changes = pending.pop(tx, set())
        if tx is not None and tx.nested:
            pending.setdefault(tx.parent, set()).update(changes)
        else:
            for owner, topic in changes:
                publish_workspace_event(owner, topic)

    def rolled_back(session):
        tx = session.get_nested_transaction() or session.get_transaction()
        session.info.get(key, {}).pop(tx, None)

    def ended(session, tx):
        pending = session.info.get(key, {})
        pending.pop(tx, None)
        if not pending:
            session.info.pop(key, None)

    event.listen(factory, 'before_flush', collect)
    event.listen(factory, 'do_orm_execute', bulk)
    event.listen(factory, 'after_commit', committed)
    event.listen(factory, 'after_rollback', rolled_back)
    event.listen(factory, 'after_transaction_end', ended)
