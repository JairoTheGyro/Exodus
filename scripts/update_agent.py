#!/usr/bin/env python3
"""Exodus update helper: installs updates an admin approves in Exodus.

Exodus runs in Docker and can't update itself. This small helper runs on the
server itself (outside Docker), watches for an approved update, and installs
it with scripts/update_local.py, which backs up data first, keeps a rollback
image, and only fast-forwards to the official Exodus main branch, and only to
the exact version the admin approved.

Set it up once, from the Exodus folder on the server:

    python3 scripts/update_agent.py install     # start now and at every login/boot
    python3 scripts/update_agent.py status      # is it running? what's installed?
    python3 scripts/update_agent.py uninstall   # stop and remove it

It uses Python's standard library only. It talks to Exodus through files in
data/exodus-update/ (or $APP_DATA_DIR/exodus-update/); nothing listens on the
network. Logs: ~/Library/Logs/exodus-update-helper.log on a Mac, or
`journalctl --user -u exodus-update-helper` on Linux.
"""
import argparse
import importlib.util
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r'^[0-9a-f]{40}$')
POLL_SECONDS = 20
REQUEST_TTL = timedelta(hours=1)
UPDATE_TIMEOUT = 2 * 3600
LABEL = 'com.exodus.update-helper'
UNIT = 'exodus-update-helper.service'


def now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.replace(microsecond=0).isoformat()


def data_dir(root=ROOT):
    spec = importlib.util.spec_from_file_location('exodus_host_hardware', root / 'scripts' / 'host_hardware.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.data_dir(root)


def folder(root=ROOT):
    return data_dir(root) / 'exodus-update'


def read(path):
    try:
        if path.stat().st_size > 100_000:
            return {}
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=1)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def git_head(root=ROOT):
    out = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=30)
    head = out.stdout.strip()
    return head if out.returncode == 0 and SHA.match(head) else None


def record_installed(root=ROOT):
    head = git_head(root)
    if head:
        write(folder(root) / 'installed.json', {'revision': head, 'recorded_at': iso(now())})
    return head


def heartbeat(root=ROOT):
    write(folder(root) / 'helper.json', {'seen_at': iso(now()), 'platform': platform.system().lower(), 'version': 1})


def valid_request(data, current):
    """The approved update, if it's well-formed, recent and not handled yet."""
    target, request_id = str(data.get('target') or ''), str(data.get('id') or '')
    if not SHA.match(target) or not re.fullmatch(r'[0-9a-f]{8,64}', request_id):
        return None
    try:
        when = datetime.fromisoformat(str(data.get('requested_at')).replace('Z', '+00:00'))
    except ValueError:
        return None
    if when.tzinfo is None or not (timedelta(minutes=-5) < now() - when < REQUEST_TTL):
        return None
    if current.get('id') == request_id and current.get('state') in {'running', 'done', 'failed'}:
        return None
    return {'id': request_id, 'target': target}


def clean_lines(text, limit=30):
    lines = [re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', line).strip()[:300] for line in text.splitlines()]
    return [line for line in lines if line][-limit:]


def apply(request, root=ROOT, run=subprocess.run):
    status_path = folder(root) / 'status.json'
    started = iso(now())
    write(status_path, {'state': 'running', 'id': request['id'], 'target': request['target'], 'started_at': started,
                        'message': 'Updating: backing up, downloading and restarting Exodus. This can take several minutes.',
                        'log': []})
    try:
        result = run([sys.executable, str(root / 'scripts' / 'update_local.py'), '--expect', request['target']],
                     cwd=str(root), capture_output=True, text=True, timeout=UPDATE_TIMEOUT)
        output, ok = (result.stdout or '') + (result.stderr or ''), result.returncode == 0
    except subprocess.TimeoutExpired:
        output, ok = 'The update took too long and was stopped.', False
    log = clean_lines(output)
    installed = record_installed(root)
    if ok and installed == request['target']:
        state, message = 'done', 'Exodus is up to date. Reload the page.'
    else:
        stopped = next((line for line in reversed(log) if line.startswith('Update stopped:')), '')
        state = 'failed'
        message = (stopped or 'The update did not finish.') + ' Your data was backed up first. To go back, run python3 scripts/update_local.py --rollback on the server.'
    write(status_path, {'state': state, 'id': request['id'], 'target': request['target'], 'started_at': started,
                        'finished_at': iso(now()), 'message': message, 'log': log})
    return state


def tick(root=ROOT, run=subprocess.run):
    """One round: heartbeat, installed version, and any approved update. Returns the update result, if any."""
    heartbeat(root)
    record_installed(root)
    request_path = folder(root) / 'request.json'
    if not request_path.exists():
        return None
    request = valid_request(read(request_path), read(folder(root) / 'status.json'))
    try:
        request_path.unlink()
    except OSError:
        pass
    if not request:
        return None
    return apply(request, root, run)


def run_forever(root=ROOT):
    print(f'Exodus update helper watching {folder(root)}', flush=True)
    while True:
        try:
            if tick(root) is not None:
                # New code may have arrived with the update; let the service manager restart us.
                print('Update finished; restarting the helper.', flush=True)
                return 0
        except Exception as exc:  # keep going; report on the next round
            print(f'Update helper error: {exc}', flush=True)
        time.sleep(POLL_SECONDS)


def launchd_plist(root=ROOT, python=sys.executable):
    log = Path.home() / 'Library' / 'Logs' / 'exodus-update-helper.log'
    args = ''.join(f'\n    <string>{x}</string>' for x in (python, str(root / 'scripts' / 'update_agent.py'), 'run'))
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key><array>{args}
  </array>
  <key>WorkingDirectory</key><string>{root}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/Applications/Docker.app/Contents/Resources/bin</string>
  </dict>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict>
</plist>
'''


def systemd_unit(root=ROOT, python=sys.executable):
    return f'''[Unit]
Description=Exodus update helper (installs updates approved in Exodus)
After=network-online.target docker.service

[Service]
WorkingDirectory={root}
ExecStart={python} {root / 'scripts' / 'update_agent.py'} run
Restart=always
RestartSec=30

[Install]
WantedBy=default.target
'''


def service_file(system=None):
    system = system or platform.system()
    if system == 'Darwin':
        return Path.home() / 'Library' / 'LaunchAgents' / f'{LABEL}.plist'
    if system == 'Linux':
        return Path.home() / '.config' / 'systemd' / 'user' / UNIT
    return None


def install(root=ROOT, run=subprocess.run, system=None):
    system = system or platform.system()
    path = service_file(system)
    if path is None:
        print('Automatic setup works on macOS and Linux. On this computer, update with: python3 scripts/update_local.py')
        return 1
    if not shutil_which('docker'):
        print('Docker was not found. Install Docker first; the helper uses it to restart Exodus.')
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    if system == 'Darwin':
        path.write_text(launchd_plist(root), encoding='utf-8')
        domain = f'gui/{os.getuid()}'
        run(['launchctl', 'bootout', domain, str(path)], capture_output=True)
        result = run(['launchctl', 'bootstrap', domain, str(path)], capture_output=True, text=True)
    else:
        path.write_text(systemd_unit(root), encoding='utf-8')
        run(['systemctl', '--user', 'daemon-reload'], capture_output=True)
        result = run(['systemctl', '--user', 'enable', '--now', UNIT], capture_output=True, text=True)
    if result.returncode != 0:
        print(f'The helper file was written to {path}, but starting it failed: {(result.stderr or "").strip()[:300]}')
        return 1
    heartbeat(root)
    record_installed(root)
    print('The Exodus update helper is running. Exodus can now install tested updates with one click '
          '(Settings → License Tracker → Updates).')
    if system == 'Linux':
        print('To keep it running when nobody is logged in, run once: sudo loginctl enable-linger "$USER"')
    return 0


def uninstall(run=subprocess.run, system=None):
    system = system or platform.system()
    path = service_file(system)
    if path is None or not path.exists():
        print('The update helper is not installed.')
        return 0
    if system == 'Darwin':
        run(['launchctl', 'bootout', f'gui/{os.getuid()}', str(path)], capture_output=True)
    else:
        run(['systemctl', '--user', 'disable', '--now', UNIT], capture_output=True)
    path.unlink()
    print('The update helper was stopped and removed. Update with python3 scripts/update_local.py instead.')
    return 0


def shutil_which(name):
    import shutil
    return shutil.which(name)


def show_status(root=ROOT):
    helper = read(folder(root) / 'helper.json')
    status = read(folder(root) / 'status.json')
    path = service_file()
    print(f'Installed revision: {git_head(root) or "unknown"}')
    print(f'Helper set up: {"yes" if path and path.exists() else "no"}; last seen: {helper.get("seen_at") or "never"}')
    if status:
        print(f'Last update: {status.get("state")} — {status.get("message", "")}')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=['install', 'uninstall', 'status', 'run', 'once'])
    args = parser.parse_args(argv)
    if args.command == 'install':
        return install()
    if args.command == 'uninstall':
        return uninstall()
    if args.command == 'status':
        return show_status()
    if args.command == 'once':
        tick()
        return 0
    return run_forever()


if __name__ == '__main__':
    raise SystemExit(main())
