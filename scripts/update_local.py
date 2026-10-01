#!/usr/bin/env python3
"""Safely update this existing Exodus checkout and only its affected containers.

Run from any folder: python3 "/path/to/Sovereign Hub/scripts/update_local.py"
--dry-run fetches Git metadata and previews the plan without changing source or
containers. No environment values, Compose configuration, or build logs are
printed. The updater never removes data, volumes, images, or local changes.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PROJECT = 'sovereign-hub'
DEFAULT_FILES = ('docker-compose.yml', 'docker-compose.override.yml')
REMOTE = re.compile(r'^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)JairoTheGyro/Exodus(?:\.git)?/?$', re.I)
SERVICE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]*$')
OPERATOR_FILES = {'scripts/update_local.py', 'scripts/prepare_vaultwarden.py',
                  'scripts/cloud_setup.sh', 'scripts/cloud_test.py', 'requirements-cloud-test.txt'}


class UpdateError(RuntimeError):
    """Operator-facing failure that never includes raw command output."""


class Runner:
    def __init__(self, root: Path):
        self.root = root

    def run(self, args, *, timeout=120, allowed=(0,)):
        try:
            result = subprocess.run(args, cwd=self.root, capture_output=True,
                                    text=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UpdateError(f'{args[0]} could not complete. Check that it is installed and available.') from exc
        if result.returncode not in allowed:
            # Git/Docker diagnostics can contain URLs, credentials or env values.
            raise UpdateError(f'{args[0]} step failed (exit {result.returncode}). Source and saved data were not reset or deleted.')
        return result.stdout


def private_path(path):
    parts = Path(path).parts
    basename = parts[-1] if parts else ''
    return (any(p.startswith('.env') or p in {'data', 'chroma_data', 'backups'} for p in parts)
            or bool(re.search(r'\.(?:db|sqlite|sqlite3)(?:-(?:wal|shm|journal))?$|\.(?:pem|key|p12|pfx|kdbx|keystore)$', basename, re.I))
            or basename in {'secrets.env', 'id_rsa', 'id_dsa', 'id_ecdsa', 'id_ed25519'})


def json_value(raw, description):
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise UpdateError(f'Could not read {description}; no raw configuration was printed.') from exc


def git(runner, *args):
    return runner.run(['git', *args]).strip()


def changed_paths(runner, before, after):
    return [p for p in runner.run(['git', 'diff', '--name-only', '-z', before, after]).split('\0') if p]


def inspect_containers(runner):
    ids = runner.run(['docker', 'ps', '-aq', '--filter', f'label=com.docker.compose.project={PROJECT}']).split()
    if not ids:
        return []
    # Inspect only Compose identity, hash and running state, never container env.
    template = '{"service":{{json (index .Config.Labels "com.docker.compose.service")}},"hash":{{json (index .Config.Labels "com.docker.compose.config-hash")}},"files":{{json (index .Config.Labels "com.docker.compose.project.config_files")}},"directory":{{json (index .Config.Labels "com.docker.compose.project.working_dir")}},"oneoff":{{json (index .Config.Labels "com.docker.compose.oneoff")}},"running":{{json .State.Running}},"mounts":{{json .Mounts}},"image":{{json .Image}}}'
    raw = runner.run(['docker', 'inspect', '--format', template, *ids])
    containers = [json_value(line, 'container identity') for line in raw.splitlines() if line.strip()]
    images = sorted({c['image'] for c in containers if c.get('image')})
    declared = {}
    if images:
        raw = runner.run(['docker', 'image', 'inspect', '--format',
                          '{"image":{{json .Id}},"volumes":{{json (index .Config "Volumes")}}}', *images])
        for line in raw.splitlines():
            if line.strip():
                value = json_value(line, 'image volume declarations')
                declared[value['image']] = list(value.get('volumes') or {})
    desktop = 'docker desktop' in runner.run(['docker', 'info', '--format', '{{.OperatingSystem}}']).lower()
    for container in containers:
        container['image_volumes'] = declared.get(container.get('image'), [])
        container['desktop_host'] = desktop
    return containers


def compose_files(root, containers):
    choices = []
    for item in containers:
        if str(item.get('oneoff')).lower() == 'true':
            continue
        if item.get('directory') and Path(item['directory']).resolve() != root:
            raise UpdateError('This Docker project belongs to another checkout. Update it from its original folder.')
        files = [Path(p).resolve() for p in (item.get('files') or '').split(',') if p]
        if files:
            if any(not p.is_relative_to(root) or not p.is_file() for p in files):
                raise UpdateError('An active Compose file is missing or outside this checkout. Review the deployment before updating.')
            choices.append(files)
    if not choices:
        return [root / name for name in DEFAULT_FILES if (root / name).is_file()]
    longest = max(choices, key=len)
    if any(longest[:len(files)] != files for files in choices):
        raise UpdateError('Containers use conflicting Compose overlays. Reconcile their configuration before updating.')
    return longest


class Compose:
    def __init__(self, runner, root, files):
        self.runner, self.root, self.files = runner, root, files

    def command(self, *args, files=None):
        cmd = ['docker', 'compose', '--project-directory', str(self.root), '-p', PROJECT]
        for path in files or self.files:
            cmd.extend(['-f', str(path)])
        return [*cmd, *args]

    def config(self, *, files=None):
        value = json_value(self.runner.run(self.command('config', '--format', 'json', files=files)), 'Compose configuration')
        services = value.get('services', {})
        if 'odysseus' not in services or any(not SERVICE.fullmatch(name) for name in services):
            raise UpdateError('The Compose configuration does not describe a supported Exodus installation.')
        return value

    def preview(self, ref):
        # Resolve incoming Compose files before changing the checkout. The project
        # directory keeps relative mounts and the private .env at their real path.
        with tempfile.TemporaryDirectory(prefix='exodus-update-') as folder:
            paths = []
            for index, path in enumerate(self.files):
                relative = path.relative_to(self.root).as_posix()
                content = self.runner.run(['git', 'show', f'{ref}:{relative}'])
                target = Path(folder) / f'{index}.yml'
                target.write_text(content)
                paths.append(target)
            return self.config(files=paths)

    def hashes(self):
        raw = self.runner.run(self.command('config', '--hash', '*'))
        result = {}
        for line in raw.splitlines():
            fields = line.split()
            if len(fields) != 2 or not SERVICE.fullmatch(fields[0]):
                raise UpdateError('Compose service hashes were not readable. Update Docker Compose before retrying.')
            result[fields[0]] = fields[1]
        return result


def local_relative(root, value):
    if not isinstance(value, str):
        return None
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return None


def within(path, parent):
    return parent == '.' or path == parent or path.startswith(parent.rstrip('/') + '/')


def documentation_only(path):
    return (path in OPERATOR_FILES or path.startswith(('docs/', 'tests/', '.github/', 'dev-docs/', 'website/'))
            or path in {'.gitignore', '.gitattributes', 'LICENSE', 'LICENSE.txt'}
            or ('/' not in path and path.endswith('.md')))


def check_storage_changes(before, after):
    # A code updater must not silently migrate a live database or replace an
    # existing network. Those operations need their own reviewed migration.
    for kind in ('volumes', 'networks'):
        for name, previous in before.get(kind, {}).items():
            if name not in after.get(kind, {}) or previous != after[kind][name]:
                raise UpdateError(f'Existing {kind} definitions changed. Review that migration separately; no containers or data were removed.')
    for name, service in before['services'].items():
        if name not in after['services']:
            raise UpdateError('An existing service was removed. Review that migration separately; no container was removed.')
        old = {v['target']: v for v in service.get('volumes', []) if v.get('type') == 'volume' or not v.get('read_only', False)}
        new = {v['target']: v for v in after['services'][name].get('volumes', [])}
        if any(target not in new or any(value.get(k) != new[target].get(k) for k in ('type', 'source', 'read_only')) for target, value in old.items()):
            raise UpdateError('A persistent storage mount changed. Review its data migration separately before updating.')


def check_runtime_storage(config, containers):
    """Also catch an ignored .env change that points running data at a new path."""
    for container in containers:
        if str(container.get('oneoff')).lower() == 'true':
            continue
        service = config['services'].get(container.get('service'), {})
        desired = {v['target']: v for v in service.get('volumes', [])}
        named_sources = {config.get('volumes', {}).get(v.get('source', ''), {}).get('name', PROJECT + '_' + v.get('source', ''))
                         for v in desired.values() if v.get('type') == 'volume'}
        for actual in container.get('mounts', []):
            if actual.get('Type') != 'volume' and not (actual.get('Type') == 'bind' and actual.get('RW')):
                continue
            expected = desired.get(actual.get('Destination'), {})
            if not expected and actual.get('Type') == 'volume' and actual.get('Destination') in container.get('image_volumes', []):
                # Dockerfile VOLUME entries can add mounts absent from Compose.
                # Compose preserves anonymous volumes on recreate (we never use
                # --renew-anon-volumes). An inherited named alias is also safe
                # when the same volume remains explicitly mounted elsewhere.
                name = actual.get('Name', '')
                if re.fullmatch(r'[0-9a-f]{64}', name) or name in named_sources:
                    continue
            mismatch = expected.get('type') != actual.get('Type')
            if actual.get('Type') == 'volume':
                source = expected.get('source', '')
                volume_name = config.get('volumes', {}).get(source, {}).get('name', PROJECT + '_' + source)
                mismatch |= actual.get('Name') != volume_name
            else:
                mismatch |= not same_bind_source(expected.get('source'), actual.get('Source'), container.get('desktop_host', False))
            if mismatch:
                raise UpdateError('Configured storage differs from the running installation. Review the data path or volume migration before updating.')


def same_bind_source(expected, actual, desktop):
    if actual == expected:
        return True
    # Desktop exposes the same host folder through a Linux-VM path. Never apply
    # this alias on an ordinary Linux daemon, where it may be different data.
    if desktop and isinstance(actual, str) and isinstance(expected, str):
        for prefix in ('/host_mnt', '/run/desktop/mnt/host'):
            if actual.startswith(prefix + '/') and actual[len(prefix):] == expected:
                return True
    return False


def check_deleted_mounts(root, paths, tracked, config):
    for service in config['services'].values():
        for volume in service.get('volumes', []):
            source = local_relative(root, volume.get('source')) if volume.get('type') == 'bind' else None
            if source is not None and volume.get('read_only') and any(within(p, source) for p in paths):
                if not any(within(p, source) for p in tracked if p):
                    raise UpdateError('An incoming update deletes a mounted source file or directory. Correct its Compose mount before updating.')


@dataclass
class Plan:
    recreate: set[str] = field(default_factory=set)
    build: set[str] = field(default_factory=set)
    ui_changed: bool = False


def plan_update(root, paths, before, after, containers, hashes):
    check_storage_changes(before, after)
    check_runtime_storage(after, containers)
    plan = Plan()
    actual = {c.get('service'): c for c in containers if str(c.get('oneoff')).lower() != 'true'}
    for name, service in after['services'].items():
        if name not in before['services'] or before['services'][name] != service:
            plan.recreate.add(name)
            if service.get('build') != before['services'].get(name, {}).get('build') and service.get('build'):
                plan.build.add(name)
        if name in actual and actual[name].get('hash') != hashes.get(name):
            plan.recreate.add(name)

    compose_names = {p for p in paths if p.startswith(('docker-compose', 'compose.')) and p.endswith(('.yml', '.yaml'))}
    for path in paths:
        if documentation_only(path) or path in compose_names:
            continue
        mounts = set()
        for name, service in after['services'].items():
            for volume in service.get('volumes', []):
                relative = local_relative(root, volume.get('source')) if volume.get('type') == 'bind' else None
                if relative is not None and volume.get('read_only') and within(path, relative):
                    mounts.add(name)
        plan.recreate.update(mounts)
        if path.startswith('static/'):
            plan.ui_changed = True
        candidates = []
        for name, service in after['services'].items():
            build = service.get('build')
            if not build:
                continue
            relative = local_relative(root, build.get('context'))
            if relative is not None and within(path, relative):
                candidates.append((len(relative.split('/')) if relative != '.' else 0, name, relative, build))
        # Nested contexts belong to that companion, not the app's COPY . layer.
        if candidates:
            depth = max(c[0] for c in candidates)
            for rank, name, context, build in candidates:
                if rank != depth:
                    continue
                rel = path if context == '.' else path[len(context) + 1:]
                image_input = (rel == build.get('dockerfile', 'Dockerfile') or rel == '.dockerignore'
                               or rel.startswith(('requirements', 'docker/')) or rel in {'pyproject.toml', 'uv.lock', 'package.json', 'package-lock.json'})
                if image_input or (name not in mounts and not mounts):
                    plan.build.add(name)
                    plan.recreate.add(name)
    # Only start missing/stopped dependencies needed by affected services.
    pending = list(plan.recreate)
    while pending:
        name = pending.pop()
        for dependency in after['services'][name].get('depends_on', {}):
            if dependency not in plan.recreate and not actual.get(dependency, {}).get('running'):
                plan.recreate.add(dependency)
                pending.append(dependency)
    return plan


def save_state(path, applied):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.exodus-update-', delete=False) as handle:
        json.dump({'applied': applied}, handle)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def update(runner, root=ROOT, *, dry_run=False, say=print):
    root = root.resolve()
    if Path(git(runner, 'rev-parse', '--show-toplevel')).resolve() != root:
        raise UpdateError('Run the updater saved inside the Exodus checkout.')
    if git(runner, 'branch', '--show-current') != 'main':
        raise UpdateError('Switch to main before updating. No branches or local changes were changed.')
    if runner.run(['git', 'status', '--porcelain=v1', '-z', '--untracked-files=all']):
        raise UpdateError('Commit or remove outstanding source changes and untracked files first. Ignored private data is left alone.')
    origins = git(runner, 'remote', 'get-url', '--all', 'origin').splitlines()
    if len(origins) != 1 or not REMOTE.fullmatch(origins[0]):
        raise UpdateError('Origin must be the JairoTheGyro/Exodus GitHub repository. No remote was changed.')
    runner.run(['docker', 'info', '--format', '{{.ServerVersion}}'], timeout=30)
    runner.run(['docker', 'compose', 'version', '--short'], timeout=30)
    containers = inspect_containers(runner)
    compose = Compose(runner, root, compose_files(root, containers))
    before = compose.config()
    hashes = compose.hashes()
    head = git(runner, 'rev-parse', 'HEAD')
    state_path = Path(git(runner, 'rev-parse', '--git-path', 'exodus-update.json'))
    if not state_path.is_absolute():
        state_path = root / state_path
    baseline = head
    if state_path.exists():
        baseline = json_value(state_path.read_text(), 'updater checkpoint').get('applied', '')
        if not re.fullmatch(r'[a-f0-9]{40,64}', baseline):
            raise UpdateError('The updater checkpoint is invalid. Ask a maintainer to review it.')
        git(runner, 'merge-base', '--is-ancestor', baseline, head)
    say('Checking GitHub for a fast-forward update…')
    runner.run(['git', 'fetch', '--no-tags', 'origin', 'main'], timeout=180)
    target = git(runner, 'rev-parse', 'FETCH_HEAD')
    git(runner, 'merge-base', '--is-ancestor', head, target)
    tracked = runner.run(['git', 'ls-tree', '-r', '--name-only', '-z', target]).split('\0')
    if any(private_path(p) for p in tracked if p):
        raise UpdateError('The incoming revision tracks private runtime paths. Update stopped before pulling; remove those paths from Git first.')
    paths = changed_paths(runner, baseline, target)
    preview = compose.preview(target) if head != target else before
    check_deleted_mounts(root, paths, tracked, preview)
    plan = plan_update(root, paths, before, preview, containers, hashes)
    say(f'Incoming source files: {len(paths)}. Build: {", ".join(sorted(plan.build)) or "none"}. Reload: {", ".join(sorted(plan.recreate)) or "none"}.')
    if dry_run:
        say('Preview only: Git metadata fetched; source, containers, environment files and data unchanged.')
        return plan
    # Preserve a retry checkpoint before the pull/build. A failed deployment can
    # be retried even when the second run has no new Git commits to download.
    save_state(state_path, baseline)
    runner.run(['git', 'pull', '--ff-only', 'origin', 'main'], timeout=180)
    current = git(runner, 'rev-parse', 'HEAD')
    if current != target:
        raise UpdateError('GitHub changed during the update. Source was pulled, but containers were not touched; rerun to review and apply the final revision.')
    after = compose.config()
    plan = plan_update(root, paths, before, after, containers, compose.hashes())
    if plan.build:
        say('Building changed application images; existing containers remain running during the build…')
        runner.run(compose.command('build', *sorted(plan.build)), timeout=3600)
    if plan.recreate:
        say('Reloading affected services while retaining their saved data…')
        runner.run(compose.command('up', '-d', '--no-deps', '--no-build', '--pull', 'missing',
                                   '--force-recreate', '--wait', '--wait-timeout', '120',
                                   *sorted(plan.recreate)), timeout=240)
    save_state(state_path, current)
    say(f'Update complete at {current[:12]}. Saved data, environment files and Docker volumes were retained.')
    if plan.ui_changed:
        say('Refresh the Exodus browser tab to load the updated interface.')
    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Fetch remote metadata and preview without pulling or changing containers.')
    args = parser.parse_args(argv)
    try:
        update(Runner(ROOT), dry_run=args.dry_run)
    except (UpdateError, OSError) as exc:
        print(f'Update stopped: {exc}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
