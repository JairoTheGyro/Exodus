"""Test cloud runner isolation with disposable subprocesses and synthetic keys."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

SPEC = importlib.util.spec_from_file_location("exodus_cloud_runner", Path(__file__).parents[1] / "scripts/cloud_test.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_environment_omits_inherited_credentials_and_disables_dotenv(tmp_path, monkeypatch):
    for name in ("OPENAI_API_KEY", "GROQ_API_KEY", "GOOGLE_API_KEY", "GITHUB_TOKEN", "CUSTOM_PRIVATE_TOKEN",
                 "DATABASE_URL", "ODYSSEUS_DATA_DIR", "PYTHONPATH", "PYTHONSTARTUP"):
        monkeypatch.setenv(name, "synthetic-must-not-leave-parent")
    env = runner.isolated_environment(tmp_path)
    assert "synthetic-must-not-leave-parent" not in json.dumps(env)
    assert all(name not in env for name in ("OPENAI_API_KEY", "GROQ_API_KEY", "GITHUB_TOKEN", "CUSTOM_PRIVATE_TOKEN", "PYTHONSTARTUP"))
    assert str(runner.ROOT) in env["PYTHONPATH"].split(os.pathsep)
    assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert env["HF_HUB_OFFLINE"] == env["TRANSFORMERS_OFFLINE"] == "1"
    assert env["NTFY_ENABLED"] == "false"
    (tmp_path / ".env").write_text("CLOUD_TEST_DOTENV_SECRET=synthetic-file-secret\n")
    child = subprocess.run([
        sys.executable, "-c",
        "import os; from dotenv import load_dotenv; load_dotenv('.env'); "
        "assert 'CLOUD_TEST_DOTENV_SECRET' not in os.environ; print('dotenv disabled')",
    ], cwd=tmp_path, env=env, text=True, capture_output=True, timeout=15)
    assert child.returncode == 0, child.stderr
    assert child.stdout.strip() == "dotenv disabled"


def test_real_database_and_key_paths_stay_inside_each_temporary_workspace(tmp_path):
    directories = [tmp_path / "first", tmp_path / "second"]
    for directory in directories:
        directory.mkdir()
        env = runner.isolated_environment(directory)
        child = subprocess.run([
            sys.executable, "-c",
            "import json; from pathlib import Path; from src.constants import DATA_DIR, APP_KEY_FILE; "
            "from core.database import SessionLocal, Note, engine; "
            "from src.secret_storage import encrypt; encrypt('disposable test'); "
            "db=SessionLocal(); db.add(Note(id='same-id', owner='test', title='Disposable')); db.commit(); "
            "print(json.dumps({'data':DATA_DIR,'db':engine.url.database,'key':APP_KEY_FILE,'count':db.query(Note).count()})); db.close()",
        ], cwd=directory, env=env, text=True, capture_output=True, timeout=15)
        assert child.returncode == 0, child.stderr
        value = json.loads(child.stdout)
        assert value["count"] == 1
        for key in ("data", "db", "key"):
            assert Path(value[key]).resolve().is_relative_to(directory.resolve())
        assert Path(value["key"]).is_file()
        assert not (directory / "static").exists()  # No source checkout was copied.


def test_tcp_udp_and_dns_external_access_are_blocked_before_network_use(tmp_path):
    env = runner.isolated_environment(tmp_path)
    code = """
import socket, sys
from scripts.cloud_test import block_external_python_sockets
sys.addaudithook(block_external_python_sockets)
blocked = 0
for operation in ('dns', 'tcp', 'udp'):
    try:
        if operation == 'dns':
            socket.getaddrinfo('must-never-resolve.example', 443)
        elif operation == 'tcp':
            with socket.socket() as client:
                client.connect(('192.0.2.1', 443))
        else:
            with socket.socket(type=socket.SOCK_DGRAM) as client:
                client.sendto(b'test', ('192.0.2.1', 443))
    except RuntimeError as error:
        assert 'external network' in str(error)
        blocked += 1
assert blocked == 3
assert socket.getaddrinfo('localhost', 0)
print('three blocked; loopback fixtures permitted')
"""
    child = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, text=True, capture_output=True, timeout=15)
    assert child.returncode == 0, child.stderr
    assert child.stdout.strip() == "three blocked; loopback fixtures permitted"


def test_runner_rejects_local_service_socket_connections():
    try:
        runner.block_external_python_sockets("socket.connect", (object(), "/var/run/docker.sock"))
    except RuntimeError as error:
        assert "service sockets" in str(error)
    else:
        raise AssertionError("The test runner must not contact the host Docker socket")
