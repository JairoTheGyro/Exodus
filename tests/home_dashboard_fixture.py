"""Disposable full-UI Home fixture, never the operator's data or providers.

Run with the existing Exodus image, a read-only source mount, and only loopback
port 7071 published. This fixture never imports app.py or production pollers.
QA_HOST=0.0.0.0 is for that disposable Docker container only.
"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_temp = tempfile.TemporaryDirectory(prefix="exodus-dashboard-qa-")
os.environ.update(
    PYTHON_DOTENV_DISABLED="1", ODYSSEUS_DATA_DIR=_temp.name,
    DATABASE_URL="sqlite:///" + _temp.name + "/app.db",
    EXODUS_DOCUMENTS_DIR=_temp.name + "/documents",
    EXODUS_SCRATCHPAD_DIR=_temp.name,
    AUTH_ENABLED="true", LOCALHOST_BYPASS="false", NTFY_ENABLED="false",
    VAULTWARDEN_INTERNAL_URL="http://127.0.0.1:9/vault/alive",
    VAULTWARDEN_PUBLIC_URL="http://127.0.0.1:9/vault",
)

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from core.database import Base, engine
from src.home_store import database, save
from src.ai_policy import WorkspacePolicyMiddleware
from src.app_helpers import serve_html_with_nonce
from routes.home_routes import setup_home_routes
from routes.workspace_event_routes import setup_workspace_event_routes
from routes.note.note_routes import setup_note_routes
from routes.calendar_routes import setup_calendar_routes
from routes.document.document_routes import setup_document_routes

# Full-mode fixture must never start an embedding job against a real provider.
_indexing = patch("src.note_indexing.enqueue_note")
_indexing.start()
Base.metadata.create_all(engine)
with database() as conn:
    save("dashboard-qa", {"mode": "ai-free", "hidden": ["weather"]}, conn)

app = FastAPI()
app.state.auth_manager = SimpleNamespace(
    is_configured=True, is_admin=lambda _: True,
    get_privileges=lambda _: {"can_use_documents": True},
)
app.add_middleware(WorkspacePolicyMiddleware)

@app.middleware("http")
async def fixture_identity(request, call_next):
    request.state.current_user = request.headers.get("x-test-user", "dashboard-qa")
    return await call_next(request)

for router in (setup_home_routes(), setup_workspace_event_routes(),
               setup_note_routes(), setup_calendar_routes(),
               setup_document_routes(None)):
    app.include_router(router)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

@app.get("/")
def index(request: Request):
    return serve_html_with_nonce(request, str(ROOT / "static/index.html"))

@app.get("/api/auth/status")
def auth():
    return {"authenticated": True, "username": "dashboard-qa", "is_admin": True,
            "privileges": {"can_use_documents": True}}

@app.get("/api/email/accounts")
def email_accounts():
    return {"accounts": []}

@app.get("/api/email/search")
def email_search():
    return {"emails": []}

@app.get("/api/contacts/search")
def contacts():
    return {"results": []}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("QA_HOST", "127.0.0.1"), port=7071,
                log_level="warning", access_log=False)
