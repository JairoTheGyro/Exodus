"""Loopback-only Home UI QA using disposable state. No user's data or models."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from home_integration import app
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from routes.note.note_routes import setup_note_routes
from routes.calendar_routes import setup_calendar_routes
from routes.document.document_routes import setup_document_routes
from src.app_helpers import serve_html_with_nonce
from fastapi import Request
import uvicorn
app.include_router(setup_note_routes())
app.include_router(setup_calendar_routes())
app.include_router(setup_document_routes(None))
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
@app.middleware('http')
async def fixture_identity(request,call_next):
    request.scope['headers'] = list(request.scope['headers'])+[(b'x-test-user',b'admin')]
    return await call_next(request)
@app.get('/')
def index(request:Request):return serve_html_with_nonce(request,str(ROOT/'static/index.html'))
@app.get('/api/auth/status')
def auth():return {'authenticated':True,'username':'admin','is_admin':True,'privileges':{'can_use_documents':True}}
@app.get('/api/email/accounts')
def email():return {'accounts':[]}
@app.get('/api/email/search')
def email_search():return {'emails':[]}
@app.get('/api/contacts/search')
def contacts():return {'results':[]}
if __name__=='__main__':uvicorn.run(app,host='0.0.0.0',port=7071,log_level='warning')
