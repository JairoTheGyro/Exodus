#!/usr/bin/env python3
"""Measure this whole computer's memory, processor and graphics for Exodus.

When Exodus runs in Docker on a Mac or a Windows PC, it only sees the part of
the memory Docker was given, not the whole computer. Run this on the computer
itself (not inside Docker) from the Exodus folder:

    python3 scripts/host_hardware.py

It saves the result to data/host-hardware.json (or $APP_DATA_DIR), where the
Cookbook's "What Fits?" and Settings → Account → Local AI read it. Nothing is
sent anywhere. scripts/update_local.py runs it automatically on every update.

Uses only Python's standard library (works with the python3 macOS ships), and
reuses Exodus's own hardware detector so the numbers match the Cookbook.
"""
import argparse
import importlib.util
import json
import os
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_NAME = 'host-hardware.json'
FORMAT = 'exodus.host-hardware'
# Fields the Cookbook ranks with. Anything else the detector returns stays out.
KEEP = (
    'total_ram_gb', 'available_ram_gb', 'cpu_cores', 'cpu_name', 'cpu_arch',
    'has_gpu', 'gpu_name', 'gpu_vram_gb', 'gpu_count', 'gpu_cores', 'gpus',
    'gpu_groups', 'homogeneous', 'backend', 'unified_memory',
)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_detector(root=ROOT):
    """Load services/hwfit/hardware.py without importing the rest of Exodus."""
    if 'core' not in sys.modules:
        package = types.ModuleType('core')
        package.__path__ = []
        sys.modules['core'] = package
    _load('core.platform_compat', root / 'core' / 'platform_compat.py')
    return _load('exodus_host_hardware_detector', root / 'services' / 'hwfit' / 'hardware.py')


def inside_container():
    if os.path.exists('/.dockerenv'):
        return True
    try:
        with open('/proc/1/cgroup', encoding='utf-8', errors='replace') as f:
            text = f.read().lower()
        return any(marker in text for marker in ('docker', 'containerd', 'kubepods'))
    except OSError:
        return False


def data_dir(root=ROOT, environ=os.environ):
    """Exodus's data folder on this computer: $APP_DATA_DIR, .env's APP_DATA_DIR, or ./data."""
    value = environ.get('APP_DATA_DIR', '')
    env_file = root / '.env'
    if not value and env_file.is_file():
        for line in env_file.read_text(encoding='utf-8', errors='replace').splitlines():
            key, _, raw = line.strip().partition('=')
            if key.strip() == 'APP_DATA_DIR':
                value = raw.strip().strip('"').strip("'")
    path = Path(os.path.expanduser(value or 'data'))
    return path if path.is_absolute() else root / path


def snapshot(system, now=None):
    clean = {k: system[k] for k in KEEP if k in system}
    return {
        'format': FORMAT,
        'version': 1,
        'measured_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() if now is None else now)),
        'system': clean,
    }


def write_snapshot(data, folder):
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / SNAPSHOT_NAME
    fd, tmp = tempfile.mkstemp(prefix='.host-hardware.', dir=str(folder))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=1)
        os.chmod(tmp, 0o644)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return target


def describe(system):
    ram = system.get('total_ram_gb') or 0
    parts = [f"{round(ram)} GB memory"]
    if system.get('cpu_name'):
        parts.append(str(system['cpu_name']))
    if system.get('has_gpu') and system.get('gpu_vram_gb'):
        kind = 'usable by the graphics chip' if system.get('unified_memory') else 'graphics memory'
        parts.append(f"{round(system['gpu_vram_gb'])} GB {kind}")
    return ', '.join(parts)


def record(root=ROOT, say=print):
    """Measure and save. Returns the saved path, or None when skipped."""
    if inside_container():
        say('This is running inside a container, which only sees part of the computer. '
            'Run it on the computer itself instead.')
        return None
    detector = load_detector(root)
    system = detector.detect_system(fresh=True)
    if not isinstance(system, dict) or system.get('error') or not system.get('total_ram_gb'):
        say('Could not measure this computer’s hardware.')
        return None
    path = write_snapshot(snapshot(system), data_dir(root))
    say(f'This computer: {describe(system)}. Saved for Exodus ({path}).')
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args(argv)
    return 0 if record() else 1


if __name__ == '__main__':
    raise SystemExit(main())
