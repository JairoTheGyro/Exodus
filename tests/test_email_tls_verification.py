"""Real loopback TLS handshakes, with disposable certificates and no real mail."""
import socket
import ssl
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


@contextmanager
def mail_server(tmp_path, protocol, starttls, certificate):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = 'wrong.example.test' if certificate == 'wrong-host' else 'localhost'
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=2))
            .not_valid_after(now + timedelta(days=-1 if certificate == 'expired' else 2))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
            .sign(key, hashes.SHA256()))
    certfile, keyfile = tmp_path / 'cert.pem', tmp_path / 'key.pem'
    certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                         serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile, keyfile)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    listener.settimeout(5)
    commands, errors = [], []

    def serve():
        conn = None
        try:
            conn, _ = listener.accept()
            conn.settimeout(5)
            if not starttls:
                conn = context.wrap_socket(conn, server_side=True)
            conn.sendall(b'220 test SMTP\r\n' if protocol == 'smtp' else b'* OK test IMAP\r\n')
            while True:
                line = bytearray()
                while not line.endswith(b'\n'):
                    byte = conn.recv(1)
                    if not byte:
                        return
                    line.extend(byte)
                command = line.decode().strip()
                commands.append(command)
                parts = command.split()
                verb = parts[0].upper() if protocol == 'smtp' else parts[1].upper()
                tag = '' if protocol == 'smtp' else parts[0]
                if verb in ('EHLO', 'HELO'):
                    conn.sendall(b'250-test\r\n250-STARTTLS\r\n250 AUTH PLAIN\r\n')
                elif verb == 'CAPABILITY':
                    conn.sendall(f'* CAPABILITY IMAP4rev1 STARTTLS\r\n{tag} OK capability\r\n'.encode())
                elif verb == 'STARTTLS':
                    conn.sendall(b'220 ready\r\n' if protocol == 'smtp' else f'{tag} OK ready\r\n'.encode())
                    conn = context.wrap_socket(conn, server_side=True)
                elif verb in ('AUTH', 'LOGIN'):
                    conn.sendall(b'235 authenticated\r\n' if protocol == 'smtp' else f'{tag} OK login\r\n'.encode())
                elif verb == 'DATA':
                    conn.sendall(b'354 send data\r\n')
                    data = bytearray()
                    while not data.endswith(b'\r\n.\r\n'):
                        data.extend(conn.recv(1))
                    conn.sendall(b'250 accepted\r\n')
                elif verb in ('QUIT', 'LOGOUT'):
                    conn.sendall(b'221 bye\r\n' if protocol == 'smtp' else f'* BYE bye\r\n{tag} OK logout\r\n'.encode())
                    return
                else:
                    conn.sendall(b'250 ok\r\n')
        except ssl.SSLError:
            # Expected peer alert when the client rejects our certificate.
            pass
        except Exception as exc:
            errors.append(exc)
        finally:
            if conn is not None:
                conn.close()

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    try:
        yield listener.getsockname()[1], certfile, commands
    finally:
        worker.join(timeout=6)
        listener.close()
        assert not worker.is_alive(), 'TLS test server did not stop'
        assert not errors, errors


@pytest.mark.parametrize('protocol', ['imap', 'smtp'])
@pytest.mark.parametrize('starttls', [False, True])
@pytest.mark.parametrize('certificate', ['trusted', 'self-signed', 'wrong-host', 'expired'])
def test_real_mail_tls(tmp_path, monkeypatch, protocol, starttls, certificate):
    from routes import email_helpers as h
    original_context = ssl.create_default_context
    with mail_server(tmp_path, protocol, starttls, certificate) as (port, certfile, commands):
        def client_context():
            ctx = original_context()
            if certificate != 'self-signed':
                ctx.load_verify_locations(cafile=str(certfile))
            return ctx
        monkeypatch.setattr(h.ssl, 'create_default_context', client_context)
        cfg = {'imap_host': 'localhost', 'imap_port': port, 'imap_starttls': starttls,
               'imap_user': 'test', 'imap_password': 'test',
               'smtp_host': 'localhost', 'smtp_port': port,
               'smtp_security': 'starttls' if starttls else 'ssl',
               'smtp_user': 'test', 'smtp_password': 'test'}
        monkeypatch.setattr(h, '_get_email_config', lambda *args, **kwargs: cfg)
        def connect():
            if protocol == 'imap':
                conn = h._imap_connect(owner='test', timeout=3)
                conn.logout()
            else:
                h._send_smtp_message(cfg, 'a@example.test', ['b@example.test'], 'Subject: test\r\n\r\nTest', timeout=3)
        if certificate == 'trusted':
            connect()
            assert any('LOGIN' in c or 'AUTH' in c for c in commands)
        else:
            with pytest.raises(ssl.SSLCertVerificationError):
                connect()
            assert not any('LOGIN' in c or c.startswith(('AUTH', 'MAIL', 'DATA')) for c in commands)


def test_unverified_injected_context_is_rejected_before_connection(monkeypatch):
    from routes import email_helpers as h
    connect = Mock()
    monkeypatch.setattr(h.imaplib, 'IMAP4_SSL', connect)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with pytest.raises(ssl.SSLError, match='verification'):
        h._open_imap_connection('localhost', 993, starttls=False, ssl_context=context)
    connect.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('security,port', [('ssl', 465), ('starttls', 587), ('none', 25)])
async def test_password_account_test_reports_tls_failure_without_auth(monkeypatch, security, port):
    from routes import email_routes as r
    smtp = Mock()
    smtp.starttls.side_effect = ssl.SSLCertVerificationError('certificate verify failed')
    ssl_smtp = Mock(side_effect=ssl.SSLCertVerificationError('certificate verify failed'))
    plain_smtp = Mock(return_value=smtp)
    monkeypatch.setattr(r.smtplib, 'SMTP_SSL', ssl_smtp)
    monkeypatch.setattr(r.smtplib, 'SMTP', plain_smtp)
    class Request:
        async def json(self):
            return {'smtp_host': 'smtp.example.test', 'smtp_port': port, 'smtp_security': security,
                    'smtp_user': 'test', 'smtp_password': 'test'}
    endpoint = next(route.endpoint for route in r.setup_email_routes().routes if route.path == '/api/email/accounts/test')
    result = await endpoint(Request(), owner='')
    assert result['smtp']['ok'] is False
    smtp.login.assert_not_called()
    if security == 'none':
        ssl_smtp.assert_not_called()
        plain_smtp.assert_not_called()
        assert 'Unencrypted' in result['smtp']['error']
    else:
        ctx = ssl_smtp.call_args.kwargs['context'] if security == 'ssl' else smtp.starttls.call_args.kwargs['context']
        assert ctx.check_hostname is True
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert 'certificate verify failed' in result['smtp']['error']
