#!/usr/bin/env python3
"""Prepare Vaultwarden's private bind data, TLS certificate and admin secret.

Uses Docker and Python's standard library. Never prints an admin password/hash.
Run from the checkout: python3 scripts/prepare_vaultwarden.py
Existing credentials are retained. Startup is a separate Compose action.
"""
import argparse
import datetime
import json
import hashlib
import os
from pathlib import Path
import pty
import re
import secrets
import select
import subprocess
import sqlite3
import ssl
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'vaultwarden/server:latest'


def private_directory(path):
    path = Path(path)
    if path.is_symlink():
        raise RuntimeError('A private vault directory cannot be a symbolic link.')
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path.resolve()


def prepare_storage(project, destination):
    """Copy the stopped legacy volume once, with a consistent rollback archive.

    Never copy /data from the old container: it had the same volume mounted at
    both /data and /data/vaultwarden. Read the volume root exactly once instead.
    """
    destination = private_directory(destination)
    legacy = project + '_vaultwarden-data'
    legacy_exists = subprocess.run(['docker', 'volume', 'inspect', legacy],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    populated = any(destination.iterdir())
    if not populated and not legacy_exists:
        return destination
    backup_dir = private_directory(ROOT / 'backups' / 'vaultwarden')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = backup_dir / (project + '-' + stamp + '.tar')
    mount = (f'type=bind,src={destination},dst=/backup,readonly' if populated
             else f'type=volume,src={legacy},dst=/backup,readonly')
    with backup.open('xb') as output:
        result = subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--read-only',
            '--mount', mount, '--entrypoint', 'tar', IMAGE, '-C', '/backup', '-cf', '-', '.'],
            stdout=output, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError('Consistent vault backup failed; original data was not changed.')
    if not populated:
        with tempfile.TemporaryDirectory(prefix='.vault-migrate-', dir=destination.parent) as temporary:
            stage = Path(temporary) / 'data'
            stage.mkdir(mode=0o700)
            with tarfile.open(backup) as archive:
                for member in archive.getmembers():
                    target = (stage / member.name).resolve()
                    if (not target.is_relative_to(stage) or not (member.isdir() or member.isfile())):
                        raise RuntimeError('Unexpected path in vault backup; migration stopped.')
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True, mode=0o700)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                        digest = hashlib.sha256()
                        with archive.extractfile(member) as source, target.open('xb') as output:
                            while chunk := source.read(1024 * 1024):
                                digest.update(chunk)
                                output.write(chunk)
                        target.chmod(0o600)
                        with target.open('rb') as copied:
                            copied_digest = hashlib.sha256()
                            while chunk := copied.read(1024 * 1024):
                                copied_digest.update(chunk)
                            if copied_digest.digest() != digest.digest():
                                raise RuntimeError('Vault copy verification failed.')
            database = stage / 'db.sqlite3'
            if database.exists():
                from contextlib import closing
                with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
                    if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                        raise RuntimeError('Vault database integrity check failed.')
            destination.rmdir()  # Only the still-empty destination may be replaced.
            stage.rename(destination)
        print('Vault data migrated and verified. The old named volume is retained for rollback.')
    print('Consistent vault backup saved in backups/vaultwarden (private).')
    return destination


def prepare_tls(directory):
    """Create a localhost-only self-signed leaf; never install browser/OS trust."""
    directory = private_directory(directory)
    cert, key = directory / 'cert.pem', directory / 'key.pem'
    if cert.exists() or key.exists() or cert.is_symlink() or key.is_symlink():
        if not cert.is_file() or not key.is_file() or cert.is_symlink() or key.is_symlink():
            raise RuntimeError('TLS certificate/key pair is incomplete or unsafe; no key was replaced.')
        # Retain existing keys. Expiration or hostname changes require deliberate renewal.
        info = ssl._ssl._test_decode_cert(str(cert))
        names = set(info.get('subjectAltName', ()))
        required = {('DNS', 'localhost'), ('DNS', 'vaultwarden'), ('IP Address', '127.0.0.1')}
        if (not required.issubset(names)
                or ssl.cert_time_to_seconds(info['notAfter']) <= time.time() + 86400
                or ssl.cert_time_to_seconds(info['notBefore']) > time.time()):
            raise RuntimeError('Existing TLS certificate needs renewal or required hostnames.')
        detail = subprocess.run(['openssl', 'x509', '-in', str(cert), '-text', '-noout'],
                                check=True, capture_output=True, timeout=10).stdout
        if b'CA:FALSE' not in detail or b'CA:TRUE' in detail:
            raise RuntimeError('Expected a server leaf certificate, not a certificate authority.')
        public_cert = subprocess.run(['openssl', 'x509', '-in', str(cert), '-pubkey', '-noout'],
                                     check=True, capture_output=True, timeout=10).stdout
        public_key = subprocess.run(['openssl', 'pkey', '-in', str(key), '-passin', 'pass:', '-pubout'],
                                    check=True, capture_output=True, input=b'', timeout=10).stdout
        if public_cert != public_key:
            raise RuntimeError('Existing TLS certificate and key do not match.')
    else:
        with tempfile.TemporaryDirectory(prefix='.tls-', dir=directory) as temporary:
            temporary = Path(temporary)
            config = temporary / 'openssl.cnf'
            config.write_text('[req]\nprompt=no\ndistinguished_name=dn\nx509_extensions=leaf\n'
                '[dn]\nCN=Exodus Local Vault\n[leaf]\nbasicConstraints=critical,CA:FALSE\n'
                'keyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n'
                'subjectAltName=DNS:localhost,DNS:vaultwarden,IP:127.0.0.1\n')
            result = subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                '-days', '365', '-sha256', '-keyout', str(temporary / 'key.pem'),
                '-out', str(temporary / 'cert.pem'), '-config', str(config)], capture_output=True)
            if result.returncode:
                raise RuntimeError('Local TLS certificate generation failed.')
            (temporary / 'key.pem').rename(key)
            (temporary / 'cert.pem').rename(cert)
    # The enclosing directory is owner-only. Docker mounts these exact files,
    # allowing its unprivileged UID to read them without exposing the directory.
    cert.chmod(0o644)
    key.chmod(0o644)
    print('Local HTTPS files prepared. Browser/OS trust has NOT been changed.')
    return directory


def run(*args, **kwargs):
    result = subprocess.run(['docker', *args], capture_output=True, **kwargs)
    if result.returncode:
        # Docker error text can contain runtime details; do not print secrets.
        raise RuntimeError('Docker preparation step failed; inspect Docker Desktop.')
    return result.stdout


def hash_password(password):
    """Vaultwarden's built-in Argon2 hash needs a terminal, not stdin pipes."""
    master, slave = pty.openpty()
    proc = subprocess.Popen(['docker', 'run', '--rm', '-it', '--network', 'none',
                             '--entrypoint', '/vaultwarden', IMAGE, 'hash'],
                            stdin=slave, stdout=slave, stderr=slave, close_fds=True)
    os.close(slave)
    output = b''
    sent = 0
    deadline = time.monotonic() + 45
    try:
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.2)[0]:
                try: chunk = os.read(master, 8192)
                except OSError: break
                if not chunk: break
                output += chunk
                # Prompts are emitted without newlines by rpassword.
                if sent == 0 and b'Password:' in output:
                    os.write(master, (password + '\n').encode()); sent = 1
                if sent == 1 and b'Confirm Password:' in output:
                    os.write(master, (password + '\n').encode()); sent = 2
            if proc.poll() is not None: break
        if proc.poll() is None:
            proc.terminate(); proc.wait(timeout=5)
        match = re.search(rb'\$argon2id\$v=\d+\$m=\d+,t=\d+,p=\d+\$[A-Za-z0-9+/]+\$[A-Za-z0-9+/]+', output)
        if not match or proc.returncode:
            raise RuntimeError('Could not generate the protected admin token.')
        return match.group().decode()
    finally:
        os.close(master)
        if proc.poll() is None: proc.kill(); proc.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', default='sovereign-hub')
    parser.add_argument('--data-dir', type=Path, default=None)
    parser.add_argument('--tls-dir', type=Path, default=None)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}', args.project):
        parser.error('Use a simple Docker Compose project name.')
    os.umask(0o077)
    secret_volume = args.project + '_vaultwarden-secrets'
    # Save container identity to ensure we stop only the selected project.
    ids = run('ps', '-q', '--filter', 'label=com.docker.compose.project='+args.project,
              '--filter', 'label=com.docker.compose.service=vaultwarden').decode().split()
    if ids: run('stop', *ids)
    storage_prepared = False
    try:
        data_path = prepare_storage(args.project, args.data_dir or ROOT/'data'/'vaultwarden')
        storage_prepared = True
        prepare_tls(args.tls_dir or ROOT/'data'/'vaultwarden-tls')
        run('volume','create','--label','com.docker.compose.project='+args.project,
            '--label','com.docker.compose.volume=vaultwarden-secrets',secret_volume)
        # Root helper has only these dedicated volumes, no host or Docker socket.
        base = ['run','--rm','--network','none','--read-only',
                '-v',str(data_path)+':/vault-data','-v',secret_volume+':/vault-secrets',
                '--entrypoint','sh',IMAGE]
        run(*base,'-c','chown -R 1000:1000 /vault-data /vault-secrets; chmod 700 /vault-data /vault-secrets')
        present = subprocess.run(['docker',*base,'-c','test -s /vault-secrets/vaultwarden_admin_token'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode == 0
        if not present:
            credential_dir = ROOT/'data'/'vaultwarden-access'
            credential_dir.mkdir(parents=True,exist_ok=True)
            credential_dir.chmod(0o700)
            credential_file = credential_dir/(args.project+'-admin-password.txt')
            # A prior interrupted attempt may have saved the private password
            # before the secret volume write. Reuse it rather than rotating it.
            if credential_file.exists() or credential_file.is_symlink():
                info = credential_file.lstat()
                if credential_file.is_symlink() or not credential_file.is_file() or info.st_uid != os.getuid() or info.st_mode & 0o077:
                    raise RuntimeError('Existing admin password file must be a regular owner-only file.')
                password = credential_file.read_text().strip()
                if not re.fullmatch(r'[A-Za-z0-9_-]{48,128}', password):
                    raise RuntimeError('Existing admin password file is invalid; no credential was changed.')
            else:
                password = secrets.token_urlsafe(48)
                with credential_file.open('x') as output: output.write(password+'\n')
            hashed = hash_password(password)
            run('run','--rm','-i','--network','none','--read-only','-v',secret_volume+':/vault-secrets',
                '--entrypoint','sh',IMAGE,'-c',
                'set -eu; umask 077; token_tmp=/vault-secrets/.admin-token.tmp.$$; trap \'rm -f "$token_tmp"\' EXIT; cat > "$token_tmp"; chown 1000:1000 "$token_tmp"; chmod 600 "$token_tmp"; mv "$token_tmp" /vault-secrets/vaultwarden_admin_token',
                input=(hashed+'\n').encode())
            print('Admin access prepared. Password stored privately in data/vaultwarden-access; only its Argon2 hash is mounted in the vault.')
        else:
            run(*base,'-c','chmod 600 /vault-secrets/vaultwarden_admin_token')
            print('Existing admin token retained.')
        print('Preparation complete. Start with: docker compose -p '+args.project+' up -d --no-deps vaultwarden')
    except BaseException:
        if ids and not storage_prepared:
            run('start',*ids)
        elif ids:
            # Once copied, restarting the old-volume container would allow new
            # writes outside the prepared bind directory. Retry while stopped.
            print('Vault remains stopped after storage preparation. Fix the error and rerun preparation before Compose startup.')
        raise


if __name__ == '__main__': main()
