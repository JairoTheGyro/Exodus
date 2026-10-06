"""Authenticated, content-free server-sent workspace invalidations."""
import asyncio
import json
import os
import time

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from src.auth_helpers import require_user
from src.owner_identity import DEFAULT_LOCAL_OWNER
from src.workspace_events import subscribe_workspace_events


def setup_workspace_event_routes():
    router = APIRouter(prefix='/api/workspace', tags=['workspace'])

    @router.get('/events')
    async def events(request: Request):
        owner = require_user(request)
        owners = {owner}
        if not owner:
            # Existing stores use these distinct legacy identities in no-login
            # mode. Never add them for an authenticated named account.
            owners.update({DEFAULT_LOCAL_OWNER, os.getenv('ODYSSEUS_FALLBACK_OWNER', 'owner@localhost')})

        async def stream():
            # Subscribe only once response iteration starts; cancelled middleware
            # cannot strand a subscriber before the generator gets a finally.
            sub = subscribe_workspace_events(owners)
            try:
                yield 'retry: 1500\nevent: ready\ndata: {}\n\n'
                # Renew periodically so normal middleware rechecks the login.
                # This is transport renewal, not widget/data polling.
                expires = time.monotonic() + 300
                while time.monotonic() < expires and not await request.is_disconnected():
                    try:
                        topic = await asyncio.wait_for(sub.queue.get(), timeout=15)
                        yield 'event: change\ndata: ' + json.dumps({'topic': topic}) + '\n\n'
                    except asyncio.TimeoutError:
                        # Transport keepalive only. No data polling, IMAP,
                        # provider request, or database query occurs here.
                        yield ': keepalive\n\n'
            finally:
                sub.close()

        return StreamingResponse(stream(), media_type='text/event-stream', headers={
            'Cache-Control': 'no-cache, no-store', 'X-Accel-Buffering': 'no',
            'X-Content-Type-Options': 'nosniff',
        })

    return router
