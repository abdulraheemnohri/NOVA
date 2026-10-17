from contextlib import contextmanager
from fastapi.testclient import TestClient
from nova.main import app


@contextmanager
def _client(tmp_path, monkeypatch):
    from nova.config import settings
    from nova.audit import append_audit
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    monkeypatch.setattr(settings, "workspace", tmp_path / "workspace")
    token_path = tmp_path / "api.token"
    token_path.write_text("system-monitor-test-token")
    monkeypatch.setattr(settings, "api_token_file", token_path)
    append_audit(settings.audit_path, "test.start", {})
    with TestClient(app) as client:
        yield client, {"Authorization": "Bearer system-monitor-test-token"}


def test_system_metrics_endpoint_reports_resource_categories(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, headers):
        response = client.get("/api/system", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert {"processor", "ram", "swap", "storage", "battery", "gpu", "npu", "tpu"} <= body.keys()
        assert body["processor"]["logical_cores"] >= 1
        assert 0 <= body["processor"]["utilization_percent"] <= 100
        assert body["ram"]["total_bytes"] > 0
        assert isinstance(body["storage"], list)
        assert "Read-only telemetry" in body["notes"][0]


def test_system_metrics_endpoint_requires_local_api_token(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _):
        response = client.get("/api/system")
        assert response.status_code == 401



def test_sysfs_gpu_reader_parses_amd_metrics(tmp_path):
    from nova.system_monitor import _sysfs_gpus

    device = tmp_path / "card0" / "device"
    (device / "hwmon" / "hwmon0").mkdir(parents=True)
    (device / "vendor").write_text("0x1002")
    (device / "device").write_text("0x744c")
    (device / "product_name").write_text("AMD Radeon Test")
    (device / "gpu_busy_percent").write_text("42")
    (device / "mem_info_vram_total").write_text(str(16 * 1024**3))
    (device / "mem_info_vram_used").write_text(str(4 * 1024**3))
    (device / "hwmon" / "hwmon0" / "temp1_input").write_text("65000")

    result = _sysfs_gpus(tmp_path)
    assert len(result) == 1
    assert result[0]["vendor"] == "AMD"
    assert result[0]["name"] == "AMD Radeon Test"
    assert result[0]["utilization_percent"] == 42
    assert result[0]["memory_total_mb"] == 16384
    assert result[0]["memory_used_mb"] == 4096
    assert result[0]["temperature_c"] == 65


def test_sysfs_gpu_reader_supports_intel_and_ignores_other_vendors(tmp_path):
    from nova.system_monitor import _sysfs_gpus

    intel = tmp_path / "card0" / "device"
    intel.mkdir(parents=True)
    (intel / "vendor").write_text("0x8086")
    (intel / "device").write_text("0x7d55")
    (intel / "gpu_busy_percent").write_text("not-a-number")
    other = tmp_path / "card1" / "device"
    other.mkdir(parents=True)
    (other / "vendor").write_text("0x10de")
    (other / "device").write_text("0x2684")

    result = _sysfs_gpus(tmp_path)
    assert len(result) == 1
    assert result[0]["vendor"] == "Intel"
    assert result[0]["utilization_percent"] is None
    assert result[0]["telemetry"] == "Linux sysfs (best-effort)"
