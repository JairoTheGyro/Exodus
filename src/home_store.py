"""Owner-scoped dashboard state; existing Notes/Documents remain the content stores."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from src.constants import DATA_DIR

DB_PATH = Path(DATA_DIR) / 'workspace-home.sqlite3'

class _HomeConnection(sqlite3.Connection):
    """Transaction-local pending UI changes; never published before commit."""
    pass


@contextmanager
def database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH), timeout=10, factory=_HomeConnection)
    db.workspace_events = set()
    db.row_factory = sqlite3.Row
    try:
        db.execute('CREATE TABLE IF NOT EXISTS profiles (owner TEXT PRIMARY KEY, data TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS activity (id TEXT PRIMARY KEY, owner TEXT NOT NULL, body TEXT NOT NULL, created REAL NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        yield db
        db.commit()
        from src.workspace_events import publish_workspace_event
        for owner, topic in db.workspace_events:
            publish_workspace_event(owner, topic)
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def profile(owner, db=None):
    if db is None:
        with database() as conn:
            return profile(owner, conn)
    row = db.execute('SELECT data FROM profiles WHERE owner=?', (owner or '',)).fetchone()
    return json.loads(row['data']) if row else {}


def save(owner, value, db):
    previous = profile(owner, db)
    db.execute('INSERT INTO profiles VALUES (?,?) ON CONFLICT(owner) DO UPDATE SET data=excluded.data',
               (owner or '', json.dumps(value, allow_nan=False)))
    if previous != value and hasattr(db, 'workspace_events'):
        db.workspace_events.add((owner, 'profile'))
        for topic, keys in {'goals': ('goals',), 'focus': ('timer', 'focus_sessions'),
                            'documents': ('pins',), 'team': ('status', 'share_presence', 'last_seen')}.items():
            if any(previous.get(key) != value.get(key) for key in keys):
                db.workspace_events.add((owner, topic))


def ai_free(owner):
    # Missing store is the original full experience, not a migration of user data.
    if not DB_PATH.exists():
        return False
    return profile(owner).get('mode') == 'ai-free'
