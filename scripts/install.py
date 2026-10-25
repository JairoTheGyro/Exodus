#!/usr/bin/env python3
"""Set up Exodus on this computer (macOS or Linux) in one go.

Usually started by install.sh, but you can run it from the Exodus folder:

    python3 scripts/install.py              # set up and start Exodus
    python3 scripts/install.py --dry-run    # only show what would happen

It is safe to run again: an existing .env is kept (only missing essentials are
added), and Exodus is rebuilt and restarted. It:

1. checks Docker is installed and running;
2. creates .env from .env.example: invitation-only sign-in, Exodus reachable
   only from this computer (Tailscale can publish it privately), a free port,
   and the Docker project name the updater expects;
3. builds and starts Exodus and waits until it's healthy (the first build can
   take 20–60 minutes);
4. measures this computer's memory for Local AI (scripts/host_hardware.py);
5. offers to set up the update helper for one-click updates
   (scripts/update_agent.py);
6. prints the address to open and, on a brand-new install, the first admin
   account's temporary password (change it after signing in).

Standard library only; works with the python3 macOS ships.
"""
import argparse
import importlib.util
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = 'sovereign-hub'          # scripts/update_local.py expects this name
DEFAULT_PORT = 7011
MIN_FREE_GB = 20
KEY = re.compile(r'^[A-Z][A-Z0-9_]*$')


class InstallError(Exception):
    pass


class Runner:
    def run(self, args, *, timeout=120, live=False):
        """Run a command; return its output. live=True shows Docker's own progress."""
        if live:
            result = subprocess.run(args, timeout=timeout)
            if result.returncode != 0:
                raise InstallError(f'{" ".join(args[:3])} failed (see the messages above).')
            return ''
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            raise InstallError(((result.stderr or '') + (result.stdout or '')).strip()[-600:] or f'{args[0]} failed')
        return result.stdout or ''

    def which(self, name):
        return shutil.which(name)


# ── .env ─────────────────────────────────────────────────────────────────────

def set_env_value(text, key, value):
    """Set KEY=value: replace an active or commented-out line, else append."""
    if not KEY.match(key) or '\n' in str(value):
        raise ValueError('bad setting')
    lines = text.splitlines()
    for pattern in (rf'^\s*{key}\s*=', rf'^\s*#\s*{key}\s*='):
        for i, line in enumerate(lines):
            if re.match(pattern, line):
                lines[i] = f'{key}={value}'
                return '\n'.join(lines) + '\n'
    return text.rstrip('\n') + f'\n{key}={value}\n'


def env_value(text, key):
    for line in text.splitlines():
        match = re.match(rf'^\s*{key}\s*=(.*)$', line)
        if match:
            return match.group(1).strip().strip('"').strip("'")
    return None


def port_free(port):
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(('127.0.0.1', port))
        except OSError:
            return False
    return True


def choose_port(wanted=None, is_free=port_free):
    if wanted:
        return wanted
    for port in range(DEFAULT_PORT, DEFAULT_PORT + 50):
        if is_free(port):
            return port
    raise InstallError('No free port found between 7011 and 7060. Choose one with --port.')


def tailscale_name(runner):
    """This computer's private Tailscale address, if Tailscale is set up."""
    if not runner.which('tailscale'):
        return None
    try:
        data = json.loads(runner.run(['tailscale', 'status', '--json'], timeout=20) or '{}')
    except (InstallError, ValueError, subprocess.SubprocessError, OSError):
        return None
    name = str(((data.get('Self') or {}).get('DNSName')) or '').rstrip('.')
    return name if re.fullmatch(r'[a-z0-9-]+(\.[a-z0-9-]+)+', name) else None


def prepare_env(root, *, port=None, tailnet=None, is_free=port_free):
    """Returns (new .env text, what changed, port). Never drops existing settings."""
    env_path = root / '.env'
    created = not env_path.exists()
    text = env_path.read_text(encoding='utf-8') if not created else (root / '.env.example').read_text(encoding='utf-8')
    changes = []

    def ensure(key, value, *, only_if_missing):
        nonlocal text
        current = env_value(text, key)
        if only_if_missing and current not in (None, ''):
            return current
        if current != str(value):
            text = set_env_value(text, key, value)
            changes.append(f'{key}={value}')
        return str(value)

    existing_port = env_value(text, 'APP_PORT') if not created else None
    chosen = port or (int(existing_port) if existing_port and existing_port.isdigit() else choose_port(None, is_free))
    ensure('COMPOSE_PROJECT_NAME', PROJECT, only_if_missing=True)
    ensure('APP_PORT', chosen, only_if_missing=not (created or port))
    if created:
        ensure('APP_BIND', '127.0.0.1', only_if_missing=False)
        ensure('AUTH_ENABLED', 'true', only_if_missing=False)
        ensure('EXODUS_INVITE_ONLY', 'true', only_if_missing=False)
        if tailnet:
            ensure('NTFY_PUBLIC_URL', f'https://{tailnet}:8443', only_if_missing=False)
    project = env_value(text, 'COMPOSE_PROJECT_NAME')
    if project != PROJECT:
        raise InstallError(f'.env sets COMPOSE_PROJECT_NAME={project}, but the updater needs {PROJECT}. '
                           'Change it, or remove the line, then run the installer again.')
    return text, changes, int(env_value(text, 'APP_PORT')), created


def write_env(root, text):
    path = root / '.env'
    path.write_text(text, encoding='utf-8')
    os.chmod(path, 0o600)


# ── checks ───────────────────────────────────────────────────────────────────

def check_system(runner, root, system=None):
    system = system or platform.system()
    if system not in ('Darwin', 'Linux'):
        raise InstallError('This installer works on macOS and Linux. On Windows, see docs/HOME_SERVER.md.')
    for tool, hint in (('git', 'Install git first (Mac: xcode-select --install; Ubuntu: sudo apt install git).'),
                       ('docker', 'Install Docker first: Docker Desktop on a Mac, Docker Engine on Linux (docs.docker.com).')):
        if not runner.which(tool):
            raise InstallError(hint)
    try:
        runner.run(['docker', 'info', '--format', '{{.ServerVersion}}'], timeout=30)
    except InstallError as exc:
        if 'permission denied' in str(exc).lower():
            raise InstallError('Docker refused access. Run: sudo usermod -aG docker "$USER", sign out and back in, '
                               'then run the installer again.') from exc
        raise InstallError('Docker is installed but not running. Start Docker'
                           + (' Desktop' if system == 'Darwin' else '') + ', wait for it to finish starting, then run the installer again.') from exc
    try:
        runner.run(['docker', 'compose', 'version', '--short'], timeout=30)
    except InstallError as exc:
        raise InstallError('Docker Compose is missing. Install the Docker Compose plugin (docs.docker.com).') from exc
    if not (root / 'docker-compose.yml').exists() or not (root / '.env.example').exists():
        raise InstallError('Run the installer from the Exodus folder (it needs docker-compose.yml and .env.example).')
    free_gb = shutil.disk_usage(root).free / 1024 ** 3
    return free_gb


def compose(root, *args):
    return ['docker', 'compose', '--project-directory', str(root), '-p', PROJECT, *args]


def first_admin(runner, root):
    """The admin account Exodus made on its very first start, from its log."""
    try:
        log = runner.run(compose(root, 'logs', '--no-log-prefix', 'odysseus'), timeout=60)
    except (InstallError, subprocess.SubprocessError, OSError):
        return None
    user = re.findall(r'Initial admin user created \(([^)\s]+)\)', log)
    password = re.findall(r'Temporary password: (\S+)', log)
    return (user[-1], password[-1]) if user and password else None


def load_script(root, name):
    spec = importlib.util.spec_from_file_location(f'exodus_{name}', root / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ask(question, default=True, *, answer=None):
    """Yes/no from the person, even when this script's input is a pipe."""
    if answer is not None:
        return answer
    suffix = ' [Y/n] ' if default else ' [y/N] '
    try:
        with open('/dev/tty') as tty:
            sys.stdout.write(question + suffix)
            sys.stdout.flush()
            reply = tty.readline().strip().lower()
    except OSError:
        return default
    return default if not reply else reply.startswith('y')


# ── main flow ────────────────────────────────────────────────────────────────

def install(root=ROOT, *, runner=None, port=None, dry_run=False, start=True, helper=None,
            say=print, system=None, is_free=port_free):
    runner = runner or Runner()
    free_gb = check_system(runner, root, system)
    say(f'Docker is running. Free disk space: {free_gb:.0f} GB.')
    if free_gb < MIN_FREE_GB:
        say(f'Warning: the first build needs about {MIN_FREE_GB} GB free. Free some space if the build fails.')
    tailnet = tailscale_name(runner)
    text, changes, chosen_port, created = prepare_env(root, port=port, tailnet=tailnet, is_free=is_free)
    if created:
        say(f'Settings: creating .env ({", ".join(changes)}).')
    elif changes:
        say(f'Settings: keeping your .env, adding {", ".join(changes)}.')
    else:
        say('Settings: keeping your .env as it is.')
    if dry_run:
        say(f'Would build and start Exodus on port {chosen_port}, measure this computer, and offer the update helper.')
        say('Dry run: nothing was changed.')
        return {'port': chosen_port, 'tailnet': tailnet, 'changes': changes, 'dry_run': True}
    write_env(root, text)

    if start:
        say('Building and starting Exodus. The first time this can take 20–60 minutes…')
        runner.run(compose(root, 'up', '-d', '--build', '--wait'), timeout=3 * 3600, live=True)
        say('Exodus is running.')
    try:
        load_script(root, 'host_hardware').record(root, say=say)
    except Exception as exc:  # a convenience, never a reason to fail
        say(f'Could not measure this computer for Local AI: {exc}')

    want_helper = ask('Set up one-click updates (the update helper)?', True, answer=helper)
    if want_helper:
        if load_script(root, 'update_agent').install(root) != 0:
            say('The update helper was not set up. You can update with: python3 scripts/update_local.py')
    else:
        say('Skipped the update helper. Set it up later with: python3 scripts/update_agent.py install')

    admin = first_admin(runner, root) if start else None
    say('')
    say(f'Done. Open http://localhost:{chosen_port} on this computer.')
    if admin:
        say(f'Sign in as "{admin[0]}" with the temporary password {admin[1]} and change it right away '
            '(Settings → Account).')
    else:
        say('Sign in with your admin account. On a brand-new install, its temporary password is in: '
            'docker compose logs odysseus')
    if tailnet:
        say('To reach it privately from your other devices through Tailscale, run once:')
        say(f'  sudo tailscale serve --bg {chosen_port}')
        say(f'Then open https://{tailnet} on any device in your Tailscale network.')
    else:
        say('To use it from other devices, set up Tailscale: see docs/HOME_SERVER.md.')
    return {'port': chosen_port, 'tailnet': tailnet, 'changes': changes, 'dry_run': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dry-run', action='store_true', help='Only show what would happen.')
    parser.add_argument('--port', type=int, help=f'Port for Exodus on this computer (default: {DEFAULT_PORT} or the next free one).')
    parser.add_argument('--no-start', action='store_true', help='Prepare settings but do not build or start Exodus.')
    helper = parser.add_mutually_exclusive_group()
    helper.add_argument('--with-helper', dest='helper', action='store_const', const=True, help='Set up the update helper without asking.')
    helper.add_argument('--no-helper', dest='helper', action='store_const', const=False, help='Do not set up the update helper.')
    args = parser.parse_args(argv)
    if args.port is not None and not 1024 <= args.port <= 65535:
        parser.error('--port must be between 1024 and 65535')
    try:
        install(port=args.port, dry_run=args.dry_run, start=not args.no_start, helper=args.helper)
    except InstallError as exc:
        print(f'Install stopped: {exc}')
        return 1
    except subprocess.TimeoutExpired:
        print('Install stopped: Docker took too long. Run the installer again; it continues where it stopped.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
