"""Read-only health and launch configuration for the isolated Vaultwarden service.

This module never handles vault credentials, items, device sessions, Docker's
socket, or the vault data directory. Server health cannot establish client sync.
"""
import asyncio
import json
import os
import re
import ssl
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import httpx


DEFAULT_INTERNAL_URL = "https://vaultwarden:80/alive"
DEFAULT_PUBLIC_URL = "https://127.0.0.1:8092/"
HEALTH_TIMEOUT_SECONDS = 3.0
MAX_HEALTH_BYTES = 2048
START_COMMAND = "docker compose -p sovereign-hub up -d --no-deps vaultwarden"
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.I)


class VaultwardenConfigError(ValueError):
    """An operator setting is invalid; its value must never enter a response."""


def _validated_url(value, *, internal=False):
    # urlsplit silently strips some control characters. Reject before parsing,
    # and accept only exact paths so escapes cannot change the proxy target.
    if (not isinstance(value, str) or not value or len(value) > 2048
            or any(ord(char) <= 32 or ord(char) == 127 for char in value)
            or any(char in value for char in "\\?#%")):
        raise VaultwardenConfigError("Invalid Vaultwarden connection settings")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
        if (parsed.scheme not in {"http", "https"} or not host
                or parsed.username is not None or parsed.password is not None
                or port == 0):
            raise ValueError
        if host not in _LOOPBACK_HOSTS and not (
                len(host) <= 253 and all(_DNS_LABEL.fullmatch(label) for label in host.split("."))):
            raise ValueError
        if internal:
            if host not in _LOOPBACK_HOSTS | {"vaultwarden"} or parsed.path not in {"/alive", "/vault/alive"}:
                raise ValueError
        else:
            if parsed.scheme == "http" and host not in _LOOPBACK_HOSTS:
                raise ValueError
            if parsed.path not in {"", "/", "/vault", "/vault/"}:
                raise ValueError
    except (ValueError, UnicodeError):
        raise VaultwardenConfigError("Invalid Vaultwarden connection settings") from None
    path = parsed.path if internal else ("/vault/" if parsed.path.startswith("/vault") else "/")
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), path, "", ""))


class VaultwardenService:
    def __init__(self, transport=None):
        # A transport can be supplied by isolated tests; routes cannot supply it.
        self.transport = transport

    def connection_urls(self):
        return (
            _validated_url(os.getenv("VAULTWARDEN_INTERNAL_URL", DEFAULT_INTERNAL_URL), internal=True),
            _validated_url(os.getenv("VAULTWARDEN_PUBLIC_URL", DEFAULT_PUBLIC_URL)),
        )

    def tls_context(self):
        # Add the operator-provided local certificate to normal system trust.
        # Never disable chain verification or hostname checking for localhost.
        context = ssl.create_default_context()
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        certificate = os.getenv('VAULTWARDEN_CA_FILE', '').strip()
        if certificate:
            try:
                context.load_verify_locations(cafile=certificate)
            except (OSError, ValueError):
                raise VaultwardenConfigError('Invalid Vaultwarden trust settings') from None
        return context

    @staticmethod
    def registration_allowed():
        value = os.getenv('VAULTWARDEN_SIGNUPS_ALLOWED', 'false').strip().lower()
        if value not in {'true', 'false', '1', '0', 'yes', 'no', 'on', 'off'}:
            raise VaultwardenConfigError('Invalid Vaultwarden deployment settings')
        return value in {'true', '1', 'yes', 'on'}

    def client_config(self):
        _, public_url = self.connection_urls()
        # Explicit allowlist: never return an environment mapping or admin token.
        # These booleans describe the shipped deployment settings. Vaultwarden's
        # own authenticated admin can change its policy independently of Exodus.
        return {
            "vault_url": public_url,
            "launch_path": "/vault",
            "access_mode": "https" if public_url.startswith("https:") else "local",
            "registration_allowed": self.registration_allowed(),
            "registration_policy_source": "deployment",
            "embedded": False,
            "start_command": START_COMMAND,
            "admin_enabled": True,
        }

    async def _ping(self, url):
        # No environment proxy, redirect following, cookies, or browser headers.
        # The short streaming body limit prevents a faulty service from filling
        # memory; the outer deadline also bounds slow trickle responses.
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(HEALTH_TIMEOUT_SECONDS),
            follow_redirects=False,
            trust_env=False,
            verify=self.tls_context(),
            transport=self.transport,
        ) as client:
            headers = {"Accept": "application/json"}
            async with client.stream("GET", url, headers=headers) as response:
                if response.status_code != 200:
                    return False
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_HEALTH_BYTES:
                        return False
                    body.extend(chunk)
                try:
                    heartbeat = json.loads(body)
                    if not isinstance(heartbeat, str):
                        return False
                    datetime.fromisoformat(heartbeat.replace("Z", "+00:00"))
                except (ValueError, UnicodeError, TypeError):
                    return False
                return True

    async def _probe(self, url):
        try:
            healthy = await asyncio.wait_for(self._ping(url), timeout=HEALTH_TIMEOUT_SECONDS)
            return "running" if healthy else "degraded"
        except (httpx.HTTPError, TimeoutError, OSError):
            return "offline"

    async def status(self):
        internal_url, _ = self.connection_urls()
        vault = await self._probe(internal_url)
        details = {
            "running": "Vaultwarden is responding to its health check.",
            "degraded": "Vaultwarden responded, but its health check did not pass.",
            "offline": "Vaultwarden is unavailable. Check the Vaultwarden container and its TLS certificate.",
        }
        return {
            "status": vault,
            "reachable": vault == "running",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "detail": details[vault],
            "checks": {"vault": vault},
            "sync": {
                "status": "unknown",
                "detail": "Device sync is checked after signing into the vault; server health alone cannot verify it.",
            },
        }
