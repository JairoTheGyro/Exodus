"""Best-effort ntfy delivery. No retries, private-content logging or cloud fallback."""
import asyncio
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='exodus-notify')
_slots = threading.BoundedSemaphore(32)


def _enabled(name, default='true'):
    return os.getenv(name, default).lower() in ('true', '1', 'yes')


def _destination():
    from src.integrations import load_integrations
    integrations = [i for i in load_integrations() if i.get('preset') == 'ntfy']
    if integrations:
        active = next((i for i in integrations if i.get('enabled', True) and i.get('base_url')), None)
        if not active:
            return None  # Do not bypass an explicitly disabled integration.
        return active['base_url'].rstrip('/'), active.get('api_key', '')
    return os.getenv('NTFY_BASE_URL', 'http://localhost:8080').rstrip('/'), ''


class DestinationRejected(ValueError):
    pass


def _validated_transport(url):
    from src.url_safety import check_outbound_url, _default_resolver
    from src.integrations import _PinnedAsyncTransport, _validated_ips
    resolved = []
    def resolve(host):
        resolved.extend(_default_resolver(host))
        return resolved
    block = _enabled('REMINDER_WEBHOOK_BLOCK_PRIVATE_IPS', 'false') or _enabled('INTEGRATION_API_BLOCK_PRIVATE_IPS', 'false')
    ok, _ = check_outbound_url(url, block_private=block, resolver=resolve)
    ips = _validated_ips(resolved)
    if not ok or not ips:
        raise DestinationRejected()
    return _PinnedAsyncTransport(ips)


async def dispatch_notification(message, *, title='Exodus', priority=3, tags=None,
                                topic=None, owner=None, ai=False, incognito=False):
    """Return sent/skipped/failed; never raise on delivery/configuration failure.

    Trusted callers supply owner and privacy context, not model-controlled JSON.
    Await for delivery status; use enqueue_notification in ordinary background work.
    """
    async def send():
        if not _enabled('NTFY_ENABLED') or incognito:
            return {'status': 'skipped', 'reason': 'notifications_disabled'}
        if ai:
            from src.ai_policy import require_ai
            if not owner:
                return {'status': 'skipped', 'reason': 'missing_owner'}
            require_ai(owner)
        destination = await asyncio.to_thread(_destination)
        if destination is None:
            return {'status': 'skipped', 'reason': 'integration_disabled'}
        base, token = destination
        target = topic if topic is not None else os.getenv('NTFY_DEFAULT_TOPIC', 'exodus-alerts')
        if not isinstance(target, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', target):
            raise ValueError('Invalid topic')
        if not isinstance(message, str) or not message.strip() or len(message.encode('utf-8')) > 4096:
            raise ValueError('Message must contain 1–4096 bytes')
        if isinstance(priority, bool) or priority not in (1,2,3,4,5):
            raise ValueError('Priority must be 1–5')
        if not isinstance(title, str):
            raise ValueError('Invalid title')
        clean_title = title.replace('\r',' ').replace('\n',' ').encode('ascii','replace').decode()[:200]
        headers = {'Title': clean_title, 'Priority': str(priority), 'Firebase': 'no',
                   'Cache': 'yes' if _enabled('NTFY_CACHE_MESSAGES', 'true') else 'no',
                   'Content-Type': 'text/plain; charset=utf-8'}
        if tags:
            if not isinstance(tags, list) or len(tags)>10 or any(not isinstance(t,str) or not re.fullmatch(r'[A-Za-z0-9_+-]{1,40}',t) for t in tags):
                raise ValueError('Invalid tags')
            headers['Tags'] = ','.join(tags)
        if token:
            headers['Authorization'] = f'Bearer {token}'
        url = f'{base}/{target}'
        transport = await asyncio.to_thread(_validated_transport, url)
        async with httpx.AsyncClient(timeout=3.0, follow_redirects=False, transport=transport) as client:
            response = await client.post(url, content=message.encode('utf-8'), headers=headers)
            if not response.is_success:
                return {'status': 'failed', 'reason': 'server_rejected'}
        return {'status': 'sent'}
    try:
        return await asyncio.wait_for(send(), timeout=3.0)
    except asyncio.CancelledError:
        raise
    except DestinationRejected:
        return {'status': 'failed', 'reason': 'destination_rejected'}
    except Exception:
        # Never expose tokens, notification content, URLs or server responses.
        return {'status': 'failed', 'reason': 'unavailable_or_blocked'}


def enqueue_notification(message, **kwargs):
    """Nonblocking bounded hook for task/search completion and system alerts.

    True means queued, not delivered. Saturation drops the notification rather
    than delaying the originating action. No automatic retry or disk queue.
    """
    if not _slots.acquire(blocking=False):
        return False
    try:
        future = _pool.submit(lambda: asyncio.run(dispatch_notification(message, **kwargs)))
        future.add_done_callback(lambda _: _slots.release())
        return True
    except Exception:
        _slots.release()
        return False
