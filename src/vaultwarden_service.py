"""Read-only health and launch configuration for the isolated Vaultwarden service.

This module never handles vault credentials, items, device sessions, Docker's
socket, or the vault data directory. Server health cannot establish client sync.
"""
import asyncio
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import httpx


DEFAULT_INTERNAL_URL = "http://vaultwarden:8080/vault/alive"
GATEWAY_HEALTH_URL = "http://vaultwarden-gateway:8080/vault/alive"
DEFAULT_PUBLIC_URL = "http://localhost:8092/vault/"
HEALTH_TIMEOUT_SECONDS = 3.0
MAX_HEALTH_BYTES = 2048
START_COMMAND = "docker compose -p sovereign-hub up -d --no-deps vaultwarden vaultwarden-gateway"
TLS_START_COMMAND = ("docker compose -p sovereign-hub -f docker-compose.yml "
                     "-f docker-compose.override.yml -f docker-compose.vaultwarden-tls.yml "
                     "up -d --no-deps vaultwarden vaultwarden-gateway")
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
            if host not in _LOOPBACK_HOSTS | {"vaultwarden"} or parsed.path != "/vault/alive":
                raise ValueError
        else:
            if parsed.scheme == "http" and host not in _LOOPBACK_HOSTS:
                raise ValueError
            if parsed.path not in {"/vault", "/vault/"}:
                raise ValueError
    except (ValueError, UnicodeError):
        raise VaultwardenConfigError("Invalid Vaultwarden connection settings") from None
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path if internal else "/vault/", "", ""))


class VaultwardenService:
    def __init__(self, transport=None):
        # A transport can be supplied by isolated tests; routes cannot supply it.
        self.transport = transport

    def connection_urls(self):
        return (
            _validated_url(os.getenv("VAULTWARDEN_INTERNAL_URL", DEFAULT_INTERNAL_URL), internal=True),
            _validated_url(os.getenv("VAULTWARDEN_PUBLIC_URL", DEFAULT_PUBLIC_URL)),
        )

    def gateway_health_url(self):
        value = os.getenv('VAULTWARDEN_GATEWAY_HEALTH_URL', GATEWAY_HEALTH_URL)
        if value not in ('http://vaultwarden-gateway:8080/vault/alive',
                         'http://vaultwarden-gateway:8081/vault/alive'):
            raise VaultwardenConfigError('Invalid Vaultwarden connection settings')
        return value

    def client_config(self):
        _, public_url = self.connection_urls()
        self.gateway_health_url()
        # Explicit allowlist: never return an environment mapping or admin token.
        # These booleans describe the shipped deployment settings. Vaultwarden's
        # own authenticated admin can change its policy independently of Exodus.
        return {
            "vault_url": public_url,
            "launch_path": "/vault",
            "access_mode": "https" if public_url.startswith("https:") else "local",
            "registration_allowed": False,
            "embedded": False,
            "start_command": TLS_START_COMMAND if self.gateway_health_url().endswith(":8081/vault/alive") else START_COMMAND,
            "admin_enabled": True,
        }

    async def _ping(self, url, *, gateway=False):
        # No environment proxy, redirect following, cookies, or browser headers.
        # The short streaming body limit prevents a faulty service from filling
        # memory; the outer deadline also bounds slow trickle responses.
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(HEALTH_TIMEOUT_SECONDS),
            follow_redirects=False,
            trust_env=False,
            transport=self.transport,
        ) as client:
            headers = {"Accept": "application/json"}
            if gateway:
                # The loopback gateway rejects unrelated browser Host values.
                # This fixed service probe does not reuse the caller's Host.
                headers["Host"] = "localhost"
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

    async def _probe(self, url, *, gateway=False):
        try:
            healthy = await asyncio.wait_for(self._ping(url, gateway=gateway), timeout=HEALTH_TIMEOUT_SECONDS)
            return "running" if healthy else "degraded"
        except (httpx.HTTPError, TimeoutError, OSError):
            return "offline"

    async def status(self):
        internal_url, _ = self.connection_urls()
        gateway_url = self.gateway_health_url()
        # Concurrent deadlines keep total network waiting bounded to 3 seconds.
        vault, gateway = await asyncio.gather(
            self._probe(internal_url), self._probe(gateway_url, gateway=True),
        )
        state = "running" if vault == gateway == "running" else ("offline" if vault == "offline" else "degraded")
        details = {
            "running": "Vaultwarden and its gateway are responding to their health checks.",
            "degraded": "Vaultwarden responded, but its health check did not pass.",
            "offline": "Vaultwarden is unavailable. Check the service and gateway containers.",
        }
        if vault == "running" and gateway != "running":
            details["degraded"] = "Vaultwarden is responding, but its gateway is unavailable or unhealthy."
        return {
            "status": state,
            "reachable": vault == "running",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "detail": details[state],
            "checks": {"vault": vault, "gateway": gateway},
            "sync": {
                "status": "unknown",
                "detail": "Device sync is checked after signing into the vault; server health alone cannot verify it.",
            },
        }
