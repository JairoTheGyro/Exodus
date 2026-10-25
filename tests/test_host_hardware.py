"""Whole-computer hardware for the Cookbook and Settings → Local AI.

scripts/host_hardware.py runs on the computer itself (outside Docker) and
saves data/host-hardware.json. Inside Docker, services.hwfit.hardware ranks
models against that file instead of Docker's share of the memory.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from services.hwfit import hardware

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("host_hardware_script", ROOT / "scripts" / "host_hardware.py")
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)

MAC = {
    "total_ram_gb": 36.0, "available_ram_gb": 20.0, "cpu_cores": 12, "cpu_name": "Apple M3 Pro",
    "cpu_arch": "arm64", "has_gpu": True, "gpu_name": "Apple M3 Pro", "gpu_vram_gb": 27.0,
    "gpu_count": 1, "gpu_cores": 18, "gpus": [{"index": 0, "name": "Apple M3 Pro", "vram_gb": 27.0}],
    "gpu_groups": [{"name": "Apple M3 Pro", "vram_each": 27.0, "count": 1, "indices": [0], "vram_total": 27.0}],
    "homogeneous": True, "backend": "metal", "unified_memory": True,
}


def write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_snapshot_keeps_only_hardware_fields_and_writes_readable_file(tmp_path):
    data = host.snapshot({**MAC, "probe_scope": "native", "secret": "x", "hardware_visibility_warning": {}}, now=0)
    assert data["format"] == "exodus.host-hardware" and data["measured_at"] == "1970-01-01T00:00:00Z"
    assert set(data["system"]) <= set(host.KEEP) and "secret" not in data["system"]
    target = host.write_snapshot(data, tmp_path / "data")
    assert target.name == "host-hardware.json" and oct(target.stat().st_mode & 0o777) == "0o644"
    assert json.loads(target.read_text())["system"]["total_ram_gb"] == 36.0
    assert [p.name for p in (tmp_path / "data").iterdir()] == ["host-hardware.json"]  # no temp files left


def test_data_folder_follows_app_data_dir(tmp_path):
    assert host.data_dir(tmp_path, environ={}) == tmp_path / "data"
    (tmp_path / ".env").write_text('OTHER=1\nAPP_DATA_DIR="/srv/exodus-data"\n')
    assert host.data_dir(tmp_path, environ={}) == Path("/srv/exodus-data")
    assert host.data_dir(tmp_path, environ={"APP_DATA_DIR": "mine"}) == tmp_path / "mine"


def test_record_refuses_inside_a_container(tmp_path):
    said = []
    with patch.object(host, "inside_container", return_value=True):
        assert host.record(tmp_path, say=said.append) is None
    assert "on the computer itself" in said[0]


def test_record_saves_what_the_detector_found(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "d"))
    fake = type("Detector", (), {"detect_system": staticmethod(lambda fresh=False: dict(MAC))})
    said = []
    with patch.object(host, "inside_container", return_value=False), patch.object(host, "load_detector", return_value=fake):
        path = host.record(tmp_path, say=said.append)
    assert path == tmp_path / "d" / "host-hardware.json"
    assert "36 GB memory, Apple M3 Pro, 27 GB usable by the graphics chip" in said[0]


def test_the_script_runs_with_plain_python_and_loads_only_the_detector(tmp_path):
    code = (
        "import importlib.util, sys, json\n"
        f"spec = importlib.util.spec_from_file_location('h', {str(ROOT / 'scripts' / 'host_hardware.py')!r})\n"
        "h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)\n"
        "d = h.load_detector()\n"
        "heavy = [m for m in ('httpx', 'fastapi', 'sqlalchemy', 'src.llm_core', 'core.auth') if m in sys.modules]\n"
        "print(json.dumps({'heavy': heavy, 'has': hasattr(d, 'detect_system')}))\n"
    )
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60, cwd=tmp_path)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == {"heavy": [], "has": True}


def test_load_host_snapshot_validates(tmp_path):
    good = write(tmp_path / "a.json", host.snapshot(MAC, now=0))
    system, when = hardware.load_host_snapshot(str(good))
    assert system["gpu_vram_gb"] == 27.0 and system["backend"] == "metal" and when == "1970-01-01T00:00:00Z"
    bad = [
        {"format": "other", "system": MAC},
        {"format": "exodus.host-hardware", "system": {**MAC, "total_ram_gb": "36"}},
        {"format": "exodus.host-hardware", "system": {**MAC, "total_ram_gb": 10 ** 9}},
        {"format": "exodus.host-hardware", "system": {**MAC, "backend": "rm -rf"}},
        {"format": "exodus.host-hardware", "system": {**MAC, "gpu_vram_gb": -1}},
        {"format": "exodus.host-hardware", "system": []},
    ]
    for i, data in enumerate(bad):
        assert hardware.load_host_snapshot(str(write(tmp_path / f"b{i}.json", data))) is None, data
    (tmp_path / "junk.json").write_text("{not json")
    assert hardware.load_host_snapshot(str(tmp_path / "junk.json")) is None
    assert hardware.load_host_snapshot(str(tmp_path / "missing.json")) is None
    cpu = hardware.load_host_snapshot(str(write(tmp_path / "c.json", {"format": "exodus.host-hardware", "system": {
        "total_ram_gb": 64, "cpu_name": "x" * 500, "cpu_arch": "x86_64", "has_gpu": False, "backend": "cuda"}})))[0]
    assert cpu["backend"] == "cpu_x86" and cpu["gpu_vram_gb"] is None and len(cpu["cpu_name"]) == 120
    assert cpu["available_ram_gb"] == 64


@pytest.fixture
def container_box(tmp_path, monkeypatch):
    """A Docker Desktop-like view: 7.6 GB, no GPU, inside a container."""
    snap = tmp_path / "host-hardware.json"
    monkeypatch.setattr(hardware, "_host_snapshot_path", lambda: str(snap))
    monkeypatch.setattr(hardware, "_is_containerized", lambda: True)
    monkeypatch.setattr(hardware, "_get_ram_gb", lambda: 7.6)
    monkeypatch.setattr(hardware, "_get_available_ram_gb", lambda: 6.0)
    monkeypatch.setattr(hardware, "_get_cpu_count", lambda: 4)
    monkeypatch.setattr(hardware, "_get_cpu_name", lambda: "VM")
    monkeypatch.setattr(hardware, "_get_cpu_arch", lambda: "arm64")
    for name in ("_detect_apple_silicon", "_detect_nvidia", "_detect_amd"):
        monkeypatch.setattr(hardware, name, lambda: None)
    monkeypatch.setattr(hardware.os, "name", "posix")
    return snap


def test_inside_docker_without_a_snapshot_says_how_to_measure(container_box):
    out = hardware.detect_system(fresh=True)
    assert out["probe_scope"] == "container" and out["total_ram_gb"] == 7.6
    assert "python3 scripts/host_hardware.py" in out["hardware_visibility_warning"]["message"]


def test_inside_docker_the_cookbook_uses_the_whole_computer(container_box):
    write(container_box, host.snapshot(MAC, now=0))
    out = hardware.detect_system(fresh=True)
    assert out["probe_scope"] == "host_snapshot" and out["total_ram_gb"] == 36.0
    assert out["gpu_vram_gb"] == 27.0 and out["backend"] == "metal" and out["container_ram_gb"] == 7.6
    assert "hardware_visibility_warning" not in out and out["host_measured_at"].startswith("1970-01-01")


def test_outside_docker_the_snapshot_is_ignored(container_box, monkeypatch):
    write(container_box, host.snapshot(MAC, now=0))
    monkeypatch.setattr(hardware, "_is_containerized", lambda: False)
    out = hardware.detect_system(fresh=True)
    assert out["probe_scope"] == "native" and out["total_ram_gb"] == 7.6


def test_updater_records_hardware_after_updating_not_on_preview():
    import scripts.update_local as updater
    with patch.object(updater, "update"), patch.object(updater, "record_host_hardware") as record, \
            patch.object(updater, "record_installed"):
        assert updater.main(["--dry-run"]) == 0
        record.assert_not_called()
        assert updater.main([]) == 0
        record.assert_called_once()


def test_local_ai_card_in_a_real_browser():
    if not shutil.which("node") or not (ROOT / "node_modules" / "playwright").exists():
        pytest.skip("node with the playwright package is required (npm ci)")
    result = subprocess.run(["node", "tests/browser/localAi.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: local ai card" in result.stdout


def test_local_ai_card_is_wired():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    panel = html.split('data-settings-panel="account"', 1)[1].split('data-settings-panel=', 1)[0]
    assert 'id="local-ai-card" hidden' in panel and 'id="local-ai-rows"' in panel
    assert "mountLocalAi(byId('local-ai-rows'))" in (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")
    assert "'/static/js/settings/localAi.js'" in (ROOT / "static" / "sw.js").read_text(encoding="utf-8")


def test_described_computer_is_used_even_before_the_model_list_is_downloaded(monkeypatch):
    from types import SimpleNamespace
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    import core.middleware as middleware
    import services.hwfit.models as models
    from routes.hwfit_routes import setup_hwfit_routes

    monkeypatch.setattr(middleware, "auth_disabled", lambda: False)
    monkeypatch.setattr(hardware, "detect_system", lambda **kw: {"total_ram_gb": 8.0, "available_ram_gb": 6.0,
                                                                  "has_gpu": False, "backend": "cpu_arm", "cpu_name": "Apple M1"})
    monkeypatch.setattr(models, "get_models", lambda: [])
    app = FastAPI()
    app.state.auth_manager = SimpleNamespace(is_configured=True, is_admin=lambda user: user == "root")

    @app.middleware("http")
    async def _user(request: Request, call_next):
        request.state.current_user = request.headers.get("x-test-user")
        return await call_next(request)

    app.include_router(setup_hwfit_routes())
    client = TestClient(app)
    query = "manual_mode=gpu&manual_backend=metal&manual_gpu_count=1&manual_vram_gb=27&manual_ram_gb=36"
    body = client.get(f"/api/hwfit/models?{query}", headers={"x-test-user": "root"}).json()
    assert body["catalog_empty"] is True and body["models"] == []
    assert body["system"]["total_ram_gb"] == 36.0 and body["system"]["gpu_vram_gb"] == 27.0
    assert client.get(f"/api/hwfit/models?{query}", headers={"x-test-user": "mom"}).status_code == 403


def _row(name, quality, *, fit="good", use="general", params=7.0):
    return {"name": name, "fit_level": fit, "use_case": use, "params_b": params, "scores": {"quality": quality}}


def test_recommended_picks_trusted_family_friendly_models_once_each():
    from routes.hwfit_routes import _recommended, _official_keys
    catalog = [{"name": "Qwen/Qwen3-30B-A3B-Instruct-2507"}, {"name": "google/gemma-3-27b-it"}]
    rows = [
        _row("mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit-DWQ", 90),   # conversion of an official model
        _row("mlx-community/Qwen3-30B-A3B-Instruct-2507-8bit", 89),       # same model again
        _row("mlx-community/Qwen3-30B-A3B-Instruct-2507-abliterated-4bit", 95),  # safety removed
        _row("mlx-community/Ornith-35B-6bit", 99),                        # not a copy of an official model
        _row("someone/gemma-3-27b-it-GGUF", 98),                          # unknown publisher
        _row("google/gemma-3-27b-it", 85),
        _row("Qwen/Qwen3-Embedding-8B", 97),                              # not a chat model
        _row("google/medgemma-27b-it", 97),
        _row("Qwen/Qwen3-Coder-30B-A3B-Instruct", 96, use="coding"),
        _row("google/gemma-3-4b-it", 99, fit="marginal"),                 # doesn't fit well
        _row("google/gemma-3-12b-pt", 96),                                # base model
        _row("mlx-community/gemma-3-27b-4bit", 94),                       # base model; the -it version exists
    ]
    picks = _recommended(rows, 5, _official_keys(catalog))
    assert [p["name"] for p in picks] == ["mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit-DWQ", "google/gemma-3-27b-it"]
    assert len(_recommended(rows, 1, _official_keys(catalog))) == 1


def test_official_filter_looks_past_the_first_rows(monkeypatch):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import core.middleware as middleware
    import services.hwfit.models as models
    import services.hwfit.fit as fit
    from routes.hwfit_routes import setup_hwfit_routes

    monkeypatch.setattr(middleware, "auth_disabled", lambda: True)
    monkeypatch.setattr(hardware, "detect_system", lambda **kw: {"total_ram_gb": 36.0, "available_ram_gb": 30.0,
                                                                  "has_gpu": False, "backend": "cpu_arm"})
    monkeypatch.setattr(models, "get_models", lambda: [{"name": "google/gemma-3-27b-it"}])
    seen = {}

    def rank(system, limit=50, **kw):
        seen["limit"] = limit
        rows = [_row(f"mlx-community/remix-{i}", 99) for i in range(10)] + [_row("google/gemma-3-27b-it", 50)]
        return rows[:limit]

    monkeypatch.setattr(fit, "rank_models", rank)
    app = FastAPI()
    app.state.auth_manager = SimpleNamespace(is_configured=False)
    app.include_router(setup_hwfit_routes())
    client = TestClient(app)
    body = client.get("/api/hwfit/models?official_only=true&limit=5").json()
    assert [m["name"] for m in body["models"]] == ["google/gemma-3-27b-it"] and seen["limit"] > 5
    body = client.get("/api/hwfit/models?recommended=true&limit=5").json()
    assert [m["name"] for m in body["models"]] == ["google/gemma-3-27b-it"]
    body = client.get("/api/hwfit/models?limit=5").json()
    assert len(body["models"]) == 5 and seen["limit"] == 5  # unfiltered requests unchanged
