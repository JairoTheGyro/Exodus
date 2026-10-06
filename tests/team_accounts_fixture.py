"""Disposable browser QA for real invite/login UI; no operator data or accounts."""
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from team_accounts_integration import ROOT, AuthManager, make_app
from fastapi import Request
from fastapi.staticfiles import StaticFiles
from core.middleware import SecurityHeadersMiddleware
from src.app_helpers import serve_html_with_nonce
from src.home_store import database, save
from routes.note.note_routes import setup_note_routes
from routes.calendar_routes import setup_calendar_routes
from routes.document.document_routes import setup_document_routes
from unittest.mock import patch

_indexing=patch('src.note_indexing.enqueue_note');_indexing.start()
manager=AuthManager(str(ROOT/'browser-auth.json'))
manager.setup('team-qa','disposable-team-password')
app=make_app(manager)
app.add_middleware(SecurityHeadersMiddleware)
for router in (setup_note_routes(),setup_calendar_routes(),setup_document_routes(None)):
    app.include_router(router)
with database() as db:save('team-qa',{'mode':'ai-free'},db)
source=Path(__file__).resolve().parents[1]
app.mount('/static',StaticFiles(directory=source/'static'),name='static')
@app.get('/')
async def index(request:Request):
    return serve_html_with_nonce(request,str(source/'static/index.html'))
@app.get('/login')
async def login(request:Request):
    return serve_html_with_nonce(request,str(source/'static/login.html'))

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='0.0.0.0',port=7072,log_level='error',access_log=False)
