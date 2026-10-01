#!/usr/bin/env python3
"""Prepare only Vaultwarden's volumes; back up existing data before ownership changes.

Uses Docker and Python's standard library. Never prints an admin password/hash.
Run from the checkout: python3 scripts/prepare_vaultwarden.py
Existing credentials are retained. Startup is a separate Compose action.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import pty
import re
import secrets
import select
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'vaultwarden/server:latest'


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
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}', args.project):
        parser.error('Use a simple Docker Compose project name.')
    os.umask(0o077)
    data_volume = args.project + '_vaultwarden-data'
    secret_volume = args.project + '_vaultwarden-secrets'
    # Save container identity to ensure we stop only the selected project.
    ids = run('ps', '-q', '--filter', 'label=com.docker.compose.project='+args.project,
              '--filter', 'label=com.docker.compose.service=vaultwarden').decode().split()
    if ids: run('stop', *ids)
    try:
        exists = subprocess.run(['docker','volume','inspect',data_volume],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode == 0
        if exists:
            backup_dir = ROOT/'backups'/'vaultwarden'
            backup_dir.mkdir(parents=True,exist_ok=True)
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup = backup_dir/(args.project+'-'+stamp+'.tar')
            with backup.open('xb') as output:
                result = subprocess.run(['docker','run','--rm','--network','none','--read-only',
                    '--mount',f'type=volume,src={data_volume},dst=/backup,readonly',
                    '--entrypoint','tar',IMAGE,'-C','/backup','-cf','-','.'],stdout=output,stderr=subprocess.PIPE)
            if result.returncode: raise RuntimeError('Consistent vault backup failed; original container will be restarted.')
            print('Consistent vault backup saved in backups/vaultwarden (private).')
        for suffix, volume in (('vaultwarden-data', data_volume), ('vaultwarden-secrets', secret_volume)):
            run('volume','create','--label','com.docker.compose.project='+args.project,
                '--label','com.docker.compose.volume='+suffix,volume)
        # Root helper has only these dedicated volumes, no host or Docker socket.
        base = ['run','--rm','--network','none','--read-only',
                '-v',data_volume+':/vault-data','-v',secret_volume+':/vault-secrets',
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
        print('Preparation complete. Start with: docker compose -p '+args.project+' up -d --no-deps vaultwarden vaultwarden-gateway')
    except BaseException:
        if ids: run('start',*ids)
        raise


if __name__ == '__main__': main()
