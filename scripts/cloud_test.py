#!/usr/bin/env python3
"""Focused offline cloud checks, isolated from credentials and production state.

Run after cloud_setup.sh: .venv/bin/python scripts/cloud_test.py
No Docker, browser, model, API key, real mailbox, or local service is required.
Each suite gets a fresh process, temporary working directory, and database.
The Node harnesses read existing static sources through a symlink; no source
checkout is copied. These checks do not replace the full suite or Docker E2E.
"""
from __future__ import annotations

import argparse
import importlib.util
import ipaddress
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SUITES = {
    "runner-safety": ("pytest", "tests/test_cloud_test_runner.py"),
    "vaultwarden-preparation": ("unittest", "tests/test_prepare_vaultwarden.py"),
    "local-updater": ("unittest", "tests/test_update_local.py"),
    "vaultwarden": ("unittest", "tests/vaultwarden_integration.py"),
    "notes-search": ("unittest", "tests/notes_search_integration.py"),
    "notes-organization": ("unittest", "tests/notes_organization_integration.py"),
    "notes-export": ("unittest", "tests/notes_export_integration.py"),
    "library": ("unittest", "tests/library_files_integration.py"),
    "calendar": ("unittest", "tests/calendar_quickadd_integration.py"),
    "home": ("unittest", "tests/home_integration.py"),
    "email-tls": ("pytest", "tests/test_email_tls_verification.py"),
    "email-templates": ("pytest", "tests/test_email_template_independence.py"),
    "email-smtp": ("pytest", "tests/test_email_smtp_security.py"),
    "ui-home-email": ("node", "tests/helpers/test_home_email.mjs"),
    "ui-home-calendar": ("node", "tests/helpers/test_home_calendar_updates.mjs"),
    "ui-email-ports": ("node", "tests/helpers/test_email_port_security.mjs"),
    "ui-vaultwarden": ("node", "tests/helpers/test_vaultwarden_ui.mjs"),
}


def isolated_environment(directory: Path):
    """Allowlist runtime plumbing only; never inherit API keys or auth state."""
    data = directory / "data"
    data.mkdir()
    env = {"PATH": os.defpath if "PATH" not in os.environ else os.environ["PATH"]}
    if "SYSTEMROOT" in os.environ:
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    env.update({
        "PYTHONPATH": os.pathsep.join((str(ROOT), str(ROOT / "tests"))),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
        "PYTHON_DOTENV_DISABLED": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "ODYSSEUS_DATA_DIR": str(data), "DATABASE_URL": "sqlite:///" + str(data / "test.db"),
        "EXODUS_DOCUMENTS_DIR": str(directory / "documents"),
        "ODYSSEUS_MAIL_ATTACHMENTS_DIR": str(directory / "mail-attachments"),
        "AUTH_ENABLED": "true", "LOCALHOST_BYPASS": "false",
        "TMPDIR": str(directory), "TMP": str(directory), "TEMP": str(directory),
        "XDG_CONFIG_HOME": str(directory / "config"), "XDG_CACHE_HOME": str(directory / "cache"),
        "HF_HOME": str(directory / "huggingface"), "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
        "FASTEMBED_CACHE_PATH": str(directory / "fastembed"),
        "CHROMA_HOST": "127.0.0.1", "CHROMA_PORT": "9", "CHROMADB_PORT": "9",
        "SEARXNG_BASE_URL": "http://127.0.0.1:9", "NTFY_BASE_URL": "http://127.0.0.1:9",
        "NTFY_ENABLED": "false", "EMBEDDING_URL": "http://127.0.0.1:9/v1/embeddings",
        "LLM_HOST": "127.0.0.1", "OLLAMA_BASE_URL": "http://127.0.0.1:9",
        "TZ": "UTC",
    })
    return env


def block_external_python_sockets(event, args):
    """Allow local disposable TLS fixtures, reject accidental external traffic.

    This guard is test defense in depth, not a general-purpose process sandbox.
    Node harnesses use their existing controlled fetch/DOM implementations.
    """
    if event == "socket.getaddrinfo":
        host = args[0]
    elif event in {"socket.connect", "socket.sendto"}:
        address = args[1]
        if not isinstance(address, tuple):
            raise RuntimeError("Cloud checks must not contact local service sockets")
        host = address[0]
    else:
        return
    if isinstance(host, bytes):
        host = host.decode("ascii", errors="replace")
    if host == "localhost":
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise RuntimeError("Cloud checks must not use external network connections")


def run_child(name):
    kind, relative = SUITES[name]
    path = ROOT / relative
    sys.addaudithook(block_external_python_sockets)
    if kind == "pytest":
        import pytest
        return pytest.main([
            "-q", "-p", "no:cacheprovider", "-p", "pytest_asyncio.plugin", str(path),
            "--basetemp", str(Path.cwd() / "pytest-tmp"),
        ])
    if kind != "unittest":
        raise ValueError("Node suites must run through their own interpreter")
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    if name == "notes-export" and not Path("/proc/self/statm").exists():
        # The existing RSS assertion is Linux-specific. Report this explicit
        # portability gap on macOS; Linux cloud runs the original test intact.
        method = module.ExportChecks.test_large_zip_bounded_memory_and_integrity
        module.ExportChecks.test_large_zip_bounded_memory_and_integrity = unittest.skip(
            "Linux /proc RSS check; runs in the Linux cloud environment"
        )(method)
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=SUITES, action="append", help="Run selected suites (repeatable)")
    parser.add_argument("--timeout", type=int, default=120, help="Seconds allowed per suite (default: 120)")
    parser.add_argument("--child", choices=SUITES, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child:
        return run_child(args.child)
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    selected = args.suite or list(SUITES)
    node = shutil.which("node")
    if any(SUITES[name][0] == "node" for name in selected) and not node:
        parser.error("Node is missing; use cloud_setup.sh with Node 22 or newer available")
    failures = []
    for name in selected:
        print(f"\n== {name} ==", flush=True)
        with tempfile.TemporaryDirectory(prefix=f"exodus-cloud-{name}-") as temp:
            directory = Path(temp).resolve()
            env = isolated_environment(directory)
            # Existing JS harnesses intentionally read production source using
            # static/... paths. Link just those assets, never user-data folders.
            (directory / "static").symlink_to(ROOT / "static", target_is_directory=True)
            kind, relative = SUITES[name]
            command = [node, str(ROOT / relative)] if kind == "node" else [
                sys.executable, str(Path(__file__).resolve()), "--child", name,
            ]
            try:
                result = subprocess.run(command, cwd=directory, env=env, timeout=args.timeout)
                if result.returncode:
                    failures.append(name)
            except subprocess.TimeoutExpired:
                print(f"FAIL: {name} exceeded {args.timeout} seconds", flush=True)
                failures.append(name)
    print(f"\n{len(selected) - len(failures)}/{len(selected)} focused suites passed.", flush=True)
    if failures:
        print("Failed suites: " + ", ".join(failures), flush=True)
    print("Docker/container launch, real account sync, browser rendering, and the full pytest suite are separate checks.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
