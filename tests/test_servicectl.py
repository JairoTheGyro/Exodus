"""Exodus service manager helper (services/servicectl/servicectl.py).

Docker is never called: `run` is replaced by a fake that records each argv
and answers `docker ps` from a small in-memory table of containers.
"""
import importlib.util
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location("servicectl_under_test", ROOT / "services" / "servicectl" / "servicectl.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeDocker:
    def __init__(self):
        self.calls = []
        self.containers = {}  # service -> (id, running, image)
        self.fail = set()  # argv[1] values that should fail

    def __call__(self, argv, timeout=900):
        assert isinstance(argv, list) and argv[0] == "docker"
        self.calls.append(argv)
        if argv[1] in self.fail:
            return 1, "", "boom"
        if argv[1:3] == ["ps", "-a"]:
            service = next(a.rsplit("=", 1)[1] for a in argv if a.startswith("label=com.docker.compose.service="))
            found = self.containers.get(service)
            if not found:
                return 0, "", ""
            cid, running, image = found
            return 0, f"{cid}\t{'running' if running else 'exited'}\t{image}", ""
        return 0, "", ""

    def non_ps(self):
        return [c for c in self.calls if c[1:3] != ["ps", "-a"]]


@pytest.fixture
def ctl(tmp_path, monkeypatch):
    module = load_module()
    fake = FakeDocker()
    monkeypatch.setattr(module, "run", fake)
    monkeypatch.setattr(module, "STATE_PATH", str(tmp_path / "state" / "desired.json"))
    monkeypatch.setattr(module, "PROJECT", "sovereign-hub")
    monkeypatch.setattr(module, "PROJECT_DIR", "/work/exodus")
    module.fake = fake
    return module


def wait_idle(module, name):
    for _ in range(200):
        if not module._busy.get(name):
            return
        time.sleep(0.01)
    raise AssertionError("action did not finish")


def test_allow_list_never_includes_the_app_or_the_helper(ctl):
    assert set(ctl.SERVICES) == {"searxng", "chromadb", "ntfy", "vaultwarden", "harness", "replica"}
    assert "odysseus" not in ctl.SERVICES and "servicectl" not in ctl.SERVICES
    assert ctl.ACTIONS == ("start", "stop", "remove", "reinstall")
    with pytest.raises(ValueError):
        ctl.perform("odysseus", "stop")
    with pytest.raises(ValueError):
        ctl.perform("searxng", "exec")


def test_real_run_refuses_anything_but_a_docker_argv():
    module = load_module()
    with pytest.raises(AssertionError):
        module.run("docker ps")
    with pytest.raises(AssertionError):
        module.run(["rm", "-rf", "/"])


def test_status_reports_on_off_and_removed(ctl):
    ctl.fake.containers["searxng"] = ("abc", True, "searxng/searxng:latest")
    ctl.fake.containers["chromadb"] = ("def", False, "chromadb/chroma:1")
    assert ctl.status("searxng")["state"] == "running"
    assert ctl.status("chromadb")["state"] == "stopped"
    ntfy = ctl.status("ntfy")
    assert ntfy["state"] == "removed" and ntfy["data_volumes"] == ["ntfy-cache"]
    ps = ctl.fake.calls[0]
    assert "label=com.docker.compose.project=sovereign-hub" in ps


def test_stop_then_start_an_existing_container(ctl):
    ctl.fake.containers["searxng"] = ("abc", True, "img")
    ctl.do_stop("searxng")
    assert ["docker", "stop", "abc"] in ctl.fake.calls
    assert ctl.load_state() == {"searxng": "off"}
    ctl.fake.containers["searxng"] = ("abc", False, "img")
    ctl.do_start("searxng")
    assert ["docker", "start", "abc"] in ctl.fake.calls
    assert ctl.load_state() == {"searxng": "on"}


def test_start_after_remove_recreates_with_compose_and_profile(ctl):
    ctl.do_start("replica")
    assert ctl.fake.non_ps()[-1] == [
        "docker", "compose", "-p", "sovereign-hub", "--project-directory", "/work/exodus",
        "--profile", "replica", "up", "-d", "--no-deps", "replica",
    ]


def test_remove_keeps_data_unless_asked(ctl):
    ctl.fake.containers["vaultwarden"] = ("v1", True, "vaultwarden/server:1")
    ctl.do_remove("vaultwarden")
    calls = ctl.fake.non_ps()
    assert ["docker", "rm", "-f", "v1"] in calls
    assert ["docker", "image", "rm", "vaultwarden/server:1"] in calls
    assert not any(c[1] == "volume" for c in calls)
    assert ctl.load_state() == {"vaultwarden": "removed"}


def test_delete_data_only_removes_its_named_docker_volumes(ctl):
    ctl.fake.containers["vaultwarden"] = ("v1", True, "img")
    ctl.do_remove("vaultwarden", delete_data=True)
    volume_calls = [c for c in ctl.fake.calls if c[1] == "volume"]
    assert volume_calls == [["docker", "volume", "rm", "sovereign-hub_vaultwarden-secrets"]]
    # Host folders (data/vaultwarden) are reported but never touched.
    assert not any("data/vaultwarden" in " ".join(c) for c in ctl.fake.calls)


def test_reinstall_builds_local_services_and_pulls_the_rest(ctl):
    ctl.do_reinstall("harness")
    ctl.do_reinstall("ntfy")
    tails = [c[c.index("--project-directory") + 2:] for c in ctl.fake.non_ps()]
    assert tails == [
        ["build", "harness"], ["up", "-d", "--no-deps", "--force-recreate", "harness"],
        ["pull", "ntfy"], ["up", "-d", "--no-deps", "--force-recreate", "ntfy"],
    ]
    assert ctl.load_state() == {"harness": "on", "ntfy": "on"}


def test_failed_step_is_reported_and_busy_is_cleared(ctl):
    ctl.fake.fail.add("compose")
    assert ctl.perform("ntfy", "reinstall") is True
    wait_idle(ctl, "ntfy")
    assert "download failed" in ctl._last_error["ntfy"]
    assert ctl.status("ntfy")["busy"] is None


def test_a_second_action_while_busy_is_refused(ctl):
    gate = threading.Event()
    original = ctl.do_stop
    ctl.do_stop = lambda name: gate.wait(2)
    try:
        assert ctl.perform("searxng", "stop") is True
        assert ctl.perform("searxng", "start") is False
    finally:
        gate.set()
        wait_idle(ctl, "searxng")
        ctl.do_stop = original


def test_reconcile_keeps_turned_off_services_off(ctl):
    ctl.save_state({"searxng": "off", "chromadb": "removed", "ntfy": "on"})
    ctl.fake.containers.update({
        "searxng": ("s1", True, "img"), "chromadb": ("c1", True, "img"), "ntfy": ("n1", True, "img"),
    })
    ctl.reconcile_once()
    calls = ctl.fake.non_ps()
    assert ["docker", "stop", "s1"] in calls
    assert ["docker", "rm", "-f", "c1"] in calls
    assert not any("n1" in c for c in calls)


def test_state_file_ignores_unknown_entries(ctl):
    Path(ctl.STATE_PATH).parent.mkdir(parents=True)
    Path(ctl.STATE_PATH).write_text(json.dumps({"odysseus": "off", "ntfy": "weird", "searxng": "off"}))
    assert ctl.load_state() == {"searxng": "off"}


def test_token_is_created_once_and_reused(tmp_path):
    module = load_module()
    path = tmp_path / "run" / "token"
    first = module.load_or_create_token(str(path))
    assert len(first) >= 32 and path.read_text() == first
    assert module.load_or_create_token(str(path)) == first


@pytest.fixture
def server(ctl):
    ctl.Handler.token = "t" * 40
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ctl.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def call(url, method="GET", token="t" * 40, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if data:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_http_requires_the_token(server):
    assert call(f"{server}/services", token=None)[0] == 401
    assert call(f"{server}/services", token="wrong" * 10)[0] == 401
    code, body = call(f"{server}/services")
    assert code == 200 and [s["name"] for s in body["services"]][:2] == ["searxng", "chromadb"]


def test_http_rejects_unknown_services_and_actions(server):
    assert call(f"{server}/services/odysseus/stop", method="POST")[0] == 404
    assert call(f"{server}/services/searxng/exec", method="POST")[0] == 404
    assert call(f"{server}/services/../stop", method="POST")[0] == 404


def test_http_remove_passes_delete_data_only_for_remove(server, ctl):
    seen = []
    ctl.perform = lambda name, action, delete_data=False: seen.append((name, action, delete_data)) or True
    assert call(f"{server}/services/ntfy/remove", method="POST", body={"delete_data": True})[0] == 202
    assert call(f"{server}/services/ntfy/stop", method="POST", body={"delete_data": True})[0] == 202
    assert call(f"{server}/services/ntfy/remove", method="POST", body={"delete_data": "yes"})[0] == 202
    assert seen == [("ntfy", "remove", True), ("ntfy", "stop", False), ("ntfy", "remove", False)]


def test_http_busy_is_409(server, ctl):
    ctl.perform = lambda *a, **k: False
    assert call(f"{server}/services/ntfy/start", method="POST")[0] == 409
