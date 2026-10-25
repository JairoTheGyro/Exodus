"""One-command installer: install.sh + scripts/install.py. Docker is faked;
nothing is built, started or installed."""
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("installer_script", ROOT / "scripts" / "install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class FakeRunner:
    def __init__(self, *, docker_running=True, denied=False, tools=("git", "docker"), tailscale=None):
        self.calls, self.docker_running, self.denied = [], docker_running, denied
        self.tools, self.tailscale = set(tools) | ({"tailscale"} if tailscale else set()), tailscale
        self.log = ("Starting…\n  [ok] Initial admin user created (admin)\n"
                    "        Temporary password: Tmp-Pass_123\n        ** Change it after first login. **\n")

    def which(self, name):
        return f"/usr/bin/{name}" if name in self.tools else None

    def run(self, args, *, timeout=120, live=False):
        self.calls.append(args)
        if args[:2] == ["docker", "info"]:
            if self.denied:
                raise installer.InstallError("permission denied while trying to connect to the Docker daemon socket")
            if not self.docker_running:
                raise installer.InstallError("Cannot connect to the Docker daemon")
            return "27.0.0\n"
        if args[:3] == ["docker", "compose", "version"]:
            return "2.29.0\n"
        if args[:3] == ["tailscale", "status", "--json"]:
            return json.dumps({"Self": {"DNSName": self.tailscale + "."}})
        if args[:2] == ["docker", "compose"] and "logs" in args:
            return self.log
        if args[:2] == ["docker", "compose"]:
            return ""
        raise AssertionError(f"unexpected command {args}")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A copy of the parts of an Exodus folder the installer reads."""
    root = tmp_path / "exodus"
    (root / "scripts").mkdir(parents=True)
    for name in ("docker-compose.yml", ".env.example"):
        shutil.copy(ROOT / name, root / name)
    for name in ("host_hardware.py", "update_agent.py"):
        shutil.copy(ROOT / "scripts" / name, root / "scripts" / name)
    recorded, helpers = [], []
    monkeypatch.setattr(installer, "load_script", lambda r, name: SimpleNamespace(
        record=lambda root, say: recorded.append(root),
        install=lambda root: helpers.append(root) or 0))
    return SimpleNamespace(root=root, recorded=recorded, helpers=helpers)


def run(home, runner=None, **kw):
    said = []
    kw.setdefault("helper", True)
    kw.setdefault("system", "Darwin")
    kw.setdefault("is_free", lambda port: True)
    result = installer.install(home.root, runner=runner or FakeRunner(), say=said.append, **kw)
    return result, said


def env(home):
    return (home.root / ".env").read_text()


def test_fresh_install_writes_safe_settings_and_starts(home):
    runner = FakeRunner()
    result, said = run(home, runner)
    text = env(home)
    for line in ("COMPOSE_PROJECT_NAME=sovereign-hub", "APP_PORT=7011", "APP_BIND=127.0.0.1",
                 "AUTH_ENABLED=true", "EXODUS_INVITE_ONLY=true"):
        assert line in text.splitlines(), line
    assert "NTFY_DEFAULT_TOPIC=exodus-alerts" in text  # the rest of .env.example is kept
    assert oct((home.root / ".env").stat().st_mode & 0o777) == "0o600"
    up = next(c for c in runner.calls if "up" in c)
    assert up[:6] == ["docker", "compose", "--project-directory", str(home.root), "-p", "sovereign-hub"]
    assert up[6:] == ["up", "-d", "--build", "--wait"]
    assert home.recorded == [home.root] and home.helpers == [home.root]
    assert "Done. Open http://localhost:7011 on this computer." in said
    assert any('Sign in as "admin" with the temporary password Tmp-Pass_123' in line for line in said)


def test_rerun_without_a_new_admin_points_to_the_existing_account(home):
    runner = FakeRunner()
    runner.log = "Starting…\n"
    _, said = run(home, runner)
    assert any(line.startswith("Sign in with your admin account.") for line in said)


def test_running_again_keeps_your_settings(home):
    (home.root / ".env").write_text("APP_PORT=7099\nOPENAI_API_KEY=mine\n# my note\n")
    result, said = run(home)
    text = env(home)
    assert "APP_PORT=7099" in text and "OPENAI_API_KEY=mine" in text and "# my note" in text
    assert "COMPOSE_PROJECT_NAME=sovereign-hub" in text
    assert "AUTH_ENABLED" not in text  # existing installs keep their own choices
    assert result["port"] == 7099 and "adding COMPOSE_PROJECT_NAME=sovereign-hub" in said[1]


def test_a_different_project_name_is_refused(home):
    (home.root / ".env").write_text("COMPOSE_PROJECT_NAME=exodus\n")
    with pytest.raises(installer.InstallError, match="updater needs sovereign-hub"):
        run(home)


def test_next_free_port_and_explicit_port(home):
    taken = {7011, 7012}
    result, _ = run(home, is_free=lambda port: port not in taken)
    assert result["port"] == 7013
    result, _ = run(home, port=7020)
    assert "APP_PORT=7020" in env(home).splitlines()


def test_tailscale_sets_phone_alert_address_and_explains_serve(home):
    result, said = run(home, FakeRunner(tailscale="box.tail1234.ts.net"))
    assert "NTFY_PUBLIC_URL=https://box.tail1234.ts.net:8443" in env(home).splitlines()
    assert "  sudo tailscale serve --bg 7011" in said and "Then open https://box.tail1234.ts.net" in said[-1]


def test_dry_run_changes_nothing(home):
    runner = FakeRunner()
    result, said = run(home, runner, dry_run=True)
    assert not (home.root / ".env").exists() and result["dry_run"]
    assert not any("up" in c for c in runner.calls) and not home.helpers
    assert said[-1] == "Dry run: nothing was changed."


def test_helper_can_be_skipped(home):
    _, said = run(home, helper=False, start=False)
    assert home.helpers == [] and any("update_agent.py install" in line for line in said)


@pytest.mark.parametrize("runner,system,message", [
    (FakeRunner(docker_running=False), "Darwin", "Start Docker Desktop"),
    (FakeRunner(denied=True), "Linux", "usermod -aG docker"),
    (FakeRunner(tools=("git",)), "Linux", "Install Docker first"),
    (FakeRunner(), "Windows", "macOS and Linux"),
])
def test_clear_messages_when_something_is_missing(home, runner, system, message):
    with pytest.raises(installer.InstallError, match=message):
        run(home, runner, system=system)
    assert not (home.root / ".env").exists()


def test_set_env_value_replaces_commented_lines_and_rejects_bad_keys():
    text = "# APP_PORT=7011\nOTHER=1\n"
    assert installer.set_env_value(text, "APP_PORT", 7020) == "APP_PORT=7020\nOTHER=1\n"
    assert installer.set_env_value("A=1", "B", "2") == "A=1\nB=2\n"
    with pytest.raises(ValueError):
        installer.set_env_value(text, "bad key", "x")
    with pytest.raises(ValueError):
        installer.set_env_value(text, "OK", "line\nbreak")


def test_install_sh_is_valid_and_safe():
    script = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert subprocess.run(["bash", "-n", str(ROOT / "install.sh")]).returncode == 0
    assert os.access(ROOT / "install.sh", os.X_OK) and script.startswith("#!/usr/bin/env bash")
    assert 'REPO_URL="https://github.com/JairoTheGyro/Exodus.git"' in script
    assert "--depth" not in script  # the updater needs full history
    assert "exec python3 scripts/install.py" in script and "set -euo pipefail" in script


def test_install_sh_refuses_a_folder_that_is_not_exodus(tmp_path):
    taken = tmp_path / "exodus"
    taken.mkdir()
    out = subprocess.run(["bash", "-s"], input=(ROOT / "install.sh").read_text(), capture_output=True, text=True,
                         env={**os.environ, "EXODUS_DIR": str(taken)}, timeout=30)
    if out.returncode != 0 and "missing" in out.stderr:
        pytest.skip("git, python3 or docker isn't installed here")
    assert out.returncode == 1 and "isn't an Exodus folder" in out.stderr
