#!/usr/bin/env python3
"""Verify direct Rocket TLS and the retained compatibility Compose overlay.

Uses the shared disposable harness with temporary data, a private test CA and
no gateway. Never installs system/browser trust, disables certificate checks,
creates account credentials, reads .env, or touches the live vault.
"""
from __future__ import annotations

import http.client
import json
import socket
import ssl
import unittest

from vaultwarden_e2e import IsolatedVault, assert_websocket


class IsolatedTLSVault(IsolatedVault):
    def __init__(self):
        super().__init__(compatibility_overlay=True)


class VaultwardenTLSChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vault = IsolatedTLSVault()
        cls.addClassCleanup(cls.vault.close)
        print(f"\nStarting disposable compatibility TLS project {cls.vault.project}", flush=True)
        cls.vault.start()

    def test_trusted_ca_and_matching_hostname_are_required(self):
        self.assertTrue(self.vault.context.check_hostname)
        self.assertEqual(self.vault.context.verify_mode, ssl.CERT_REQUIRED)
        self.assertEqual(self.vault.request('/alive')[0], 200)
        untrusted = http.client.HTTPSConnection('127.0.0.1', self.vault.port, context=ssl.create_default_context(), timeout=5)
        try:
            with self.assertRaises(ssl.SSLCertVerificationError):
                untrusted.request('GET', '/alive')
                untrusted.getresponse()
        finally:
            untrusted.close()
        # The TCP destination stays loopback; only the TLS hostname is wrong.
        with socket.create_connection(('127.0.0.1', self.vault.port), timeout=5) as raw:
            with self.assertRaises(ssl.SSLCertVerificationError):
                self.vault.context.wrap_socket(raw, server_hostname='wrong-host.example.invalid')

    def test_compatibility_overlay_keeps_direct_tls_and_native_headers(self):
        service = self.vault.config['services']['vaultwarden']
        self.assertNotIn('vaultwarden-gateway', self.vault.config['services'])
        self.assertEqual(service['environment']['ROCKET_PORT'], '80')
        self.assertIn('/run/tls/cert.pem', service['environment']['ROCKET_TLS'])
        status, headers, body = self.vault.request('/')
        headers = {key.lower(): value for key, value in headers.items()}
        self.assertEqual(status, 200)
        self.assertIn(b'<app-root>', body)
        self.assertEqual(headers['x-content-type-options'], 'nosniff')
        self.assertEqual(headers['x-frame-options'], 'SAMEORIGIN')
        self.assertIn("frame-ancestors 'self'", headers['content-security-policy'])
        self.assertNotIn('frame-ancestors *', headers['content-security-policy'])
        # Native HSTS is retained. The public default is an IP literal, avoiding
        # a host-wide localhost HSTS policy affecting Exodus's HTTP port.
        self.assertIn('max-age=', headers['strict-transport-security'])
        status, _, body = self.vault.request('/api/config')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['environment']['vault'].rstrip('/'), f'https://127.0.0.1:{self.vault.port}')
        self.assertEqual(self.vault.request('/api/sync')[0], 401)
        connection = http.client.HTTPConnection('127.0.0.1', self.vault.port, timeout=5)
        try:
            try:
                connection.request('GET', '/')
                response = connection.getresponse()
            except (OSError, http.client.HTTPException):
                pass  # Rocket may terminate a plaintext request at TLS framing.
            else:
                self.assertGreaterEqual(response.status, 400, 'Never serve vault content over plaintext HTTP')
        finally:
            connection.close()

    def test_verified_tls_websocket_route(self):
        assert_websocket(self, self.vault)


if __name__ == '__main__':
    try:
        result = unittest.main(verbosity=2, exit=False).result
    finally:
        instance = getattr(VaultwardenTLSChecks, 'vault', None)
        if instance: instance.close()
    raise SystemExit(0 if result.wasSuccessful() else 1)
