"""Original Library files: local disk + existing SQLite/Postgres metadata only."""
import os
import re
import stat
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from starlette.formparsers import MultiPartException
from core.database import DocumentFile, SessionLocal
from src.auth_helpers import require_privilege
from src.constants import DOCUMENT_FILES_DIR
from src.upload_handler import secure_filename
from src.upload_limits import DOCUMENT_UPLOAD_MAX_BYTES, format_byte_limit

class BoundedUploadRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def bounded(request):
            if self.path != '/api/documents/upload':
                return await original(request)
            _owner(request)  # Authorize before parsing/spooling the multipart body.
            budget = DOCUMENT_UPLOAD_MAX_BYTES + 64 * 1024
            length = request.headers.get('content-length')
            if length:
                try:
                    size = int(length)
                except ValueError:
                    raise HTTPException(400, 'Invalid Content-Length')
                if size < 0:
                    raise HTTPException(400, 'Invalid Content-Length')
                if size > budget:
                    raise HTTPException(413, 'Upload request is too large')
            receive = request._receive
            received = 0
            exceeded = False
            async def limited_receive():
                nonlocal received, exceeded
                message = await receive()
                received += len(message.get('body', b''))
                if received > budget:
                    exceeded = True
                    # The multipart parser closes its temporary files on this error.
                    raise MultiPartException('Upload request is too large')
                return message
            request._receive = limited_receive
            try:
                return await original(request)
            except Exception:
                if exceeded:
                    raise HTTPException(413, 'Upload request is too large')
                raise
            finally:
                request._receive = receive
        return bounded


router = APIRouter(route_class=BoundedUploadRoute)
FORMATS = {'.pdf':'application/pdf', '.txt':'text/plain', '.md':'text/markdown',
           '.csv':'text/csv', '.png':'image/png', '.jpg':'image/jpeg',
           '.jpeg':'image/jpeg', '.gif':'image/gif', '.webp':'image/webp',
           '.bmp':'image/bmp', '.tif':'image/tiff', '.tiff':'image/tiff',
           '.svg':'image/svg+xml', '.avif':'image/avif', '.ico':'image/vnd.microsoft.icon'}


def _root():
    root = Path(DOCUMENT_FILES_DIR)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root.resolve()


def _path(name):
    # Storage names come from the registry, but validate them independently too.
    if not re.fullmatch(r'[0-9a-f]{32}-[A-Za-z0-9_.-]{1,180}', name or ''):
        raise HTTPException(404, 'File not found')
    path = _root() / name
    if path.is_symlink():
        raise HTTPException(409, 'Stored file is not a regular file')
    return path


def _owner(request):
    return require_privilege(request, 'can_use_documents') or None


def _query(db, owner):
    query = db.query(DocumentFile)
    return query.filter(DocumentFile.owner == owner) if owner is not None else query


def _row(db, owner, id):
    if not re.fullmatch(r'[0-9a-f]{32}', id):
        raise HTTPException(404, 'File not found')
    row = _query(db, owner).filter(DocumentFile.id == id).first()
    if row is None:
        raise HTTPException(404, 'File not found')
    return row


def _metadata(row):
    return dict(id=row.id, filename=row.filename, file_size=row.file_size,
                mime_type=row.mime_type, created_at=row.created_at.isoformat(),
                deletion_pending=row.deletion_pending)


@router.get('/api/documents')
def list_files(request: Request, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    owner = _owner(request)
    with SessionLocal() as db:
        query = _query(db, owner)
        total = query.count()
        rows = query.order_by(DocumentFile.created_at.desc(), DocumentFile.id).offset(offset).limit(limit)
        return {'files': [_metadata(row) for row in rows], 'total': total,
                'max_upload_bytes': DOCUMENT_UPLOAD_MAX_BYTES, 'extensions': list(FORMATS)}


@router.post('/api/documents/upload', status_code=201)
def upload_file(request: Request, file: UploadFile = File(...)):
    owner = _owner(request)
    # Reuse the project's sanitizer; never place raw client names in a path.
    filename = secure_filename(file.filename or '')
    extension = Path(filename).suffix.lower()
    if extension not in FORMATS:
        raise HTTPException(415, 'Use PDF, TXT, MD, CSV, or a supported image format.')
    filename = filename[:160 - len(extension)].rstrip('.') + extension if len(filename) > 160 else filename
    id = uuid.uuid4().hex
    path = _path(f'{id}-{filename}')
    created = False
    try:
        # Exclusive creation prevents overwriting; O_NOFOLLOW rejects symlinks.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        created = True
        size = 0
        with os.fdopen(fd, 'wb') as output:
            while chunk := file.file.read(64 * 1024):
                size += len(chunk)
                if size > DOCUMENT_UPLOAD_MAX_BYTES:
                    raise HTTPException(413, f'File exceeds {format_byte_limit(DOCUMENT_UPLOAD_MAX_BYTES)} limit')
                output.write(chunk)
            if size == 0:
                raise HTTPException(400, 'File is empty')
            output.flush()
            os.fsync(output.fileno())
        with SessionLocal() as db:
            row = DocumentFile(id=id, owner=owner, filename=filename, storage_name=path.name,
                               file_size=size, mime_type=FORMATS[extension])
            db.add(row)
            db.flush()
            result = _metadata(row)
            db.commit()
        return result
    except BaseException:
        if created:
            path.unlink(missing_ok=True)
        raise
    finally:
        file.file.close()


class StoredFileResponse(StreamingResponse):
    def __init__(self, file, row):
        self.file = file
        super().__init__(self.chunks(), media_type=row.mime_type, headers={
            'Content-Disposition': "attachment; filename*=UTF-8''" + quote(row.filename, safe=''),
            'Content-Length': str(os.fstat(file.fileno()).st_size),
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Content-Security-Policy': "sandbox; default-src 'none'",
        })

    def chunks(self):
        while chunk := self.file.read(64 * 1024):
            yield chunk

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.file.close()


@router.get('/api/documents/{id}/download')
def download_file(request: Request, id: str):
    owner = _owner(request)
    with SessionLocal() as db:
        row = _row(db, owner, id)
        if row.deletion_pending:
            raise HTTPException(409, 'File removal is pending. Retry delete in Library.')
        path = _path(row.storage_name)
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        except FileNotFoundError:
            raise HTTPException(404, 'Stored file is missing')
        file = os.fdopen(fd, 'rb')
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise HTTPException(409, 'Stored file is not a regular file')
            return StoredFileResponse(file, row)
        except BaseException:
            file.close()
            raise


@router.delete('/api/documents/{id}')
def delete_file(request: Request, id: str):
    owner = _owner(request)
    with SessionLocal() as db:
        row = _row(db, owner, id)
        path = _path(row.storage_name)
        # Durable intent makes a disk/DB failure retryable, including after restart.
        # A pending row remains visible but cannot be downloaded or edited.
        row.deletion_pending = True
        db.commit()
        try:
            path.unlink(missing_ok=True)
            _query(db, owner).filter(DocumentFile.id == id).delete(synchronize_session=False)
            db.commit()
        except Exception:
            db.rollback()
            raise HTTPException(503, 'Removal could not finish. Retry delete in Library.')
    return {'deleted': True, 'id': id}
