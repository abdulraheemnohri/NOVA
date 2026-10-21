from contextlib import contextmanager

import pytest

from fastapi.testclient import TestClient

from nova.config import settings
from nova.main import app
from nova import huggingface


@contextmanager
def _client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "workspace", tmp_path / "workspace")
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    monkeypatch.setattr(settings, "huggingface_cache_dir", tmp_path / "models")
    monkeypatch.setattr(settings, "huggingface_token_file", tmp_path / "private" / "huggingface.token")
    settings.workspace.mkdir(parents=True, exist_ok=True)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        token = settings.api_token_file.read_text(encoding="utf-8").strip()
        client.headers.update({"Authorization": f"Bearer {token}"})
        yield client


def test_huggingface_status_does_not_expose_token(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_HUGGINGFACE_TOKEN", "secret-test-token")
    with _client(monkeypatch, tmp_path) as client:
        response = client.get("/api/models/huggingface/status")
    assert response.status_code == 200
    assert "secret-test-token" not in response.text
    assert response.json()["token_configured"] is True
    assert response.json()["storage"]["available"] is True
    assert response.json()["storage"]["free_bytes"] > 0
    assert response.json()["hard_max_download_bytes"] == settings.huggingface_max_download_bytes
    assert response.json()["max_download_gb"] == round(response.json()["max_download_bytes"] / 1_000_000_000, 3)
    assert response.json()["hard_max_download_gb"] == round(settings.huggingface_max_download_bytes / 1_000_000_000, 3)
    assert response.json()["size_unit"] == "decimal GB (1 GB = 1,000,000,000 bytes)"
    assert response.json()["inference_policy"].startswith("Hugging Face supplies files/metadata only")


def test_huggingface_search_returns_safe_model_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr(huggingface, "_hub_json", lambda url: [
        {"id": "example/tiny-model", "downloads": 42, "pipeline_tag": "text-generation",
         "tags": ["transformers", "text-generation"]},
        {"id": "example/voice-model", "likes": 3},
    ])
    with _client(monkeypatch, tmp_path) as client:
        response = client.get("/api/models/huggingface/search?q=tiny&limit=2")
    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "Hugging Face Hub"
    assert data["results"][0]["id"] == "example/tiny-model"
    assert data["download_requires_explicit_action"] is True


def test_huggingface_file_listing_marks_only_supported_artifact_types(monkeypatch, tmp_path):
    monkeypatch.setattr(huggingface, "_hub_json", lambda url: {
        "id": "example/model", "siblings": [
            {"rfilename": "model.litertlm", "size": 100},
            {"rfilename": "weights.safetensors", "size": 200},
            {"rfilename": "config.json", "size": 10},
            {"rfilename": "run.py", "size": 10},
        ]
    })
    with _client(monkeypatch, tmp_path) as client:
        response = client.get("/api/models/huggingface/files?repo_id=example/model")
    assert response.status_code == 200
    files = {item["filename"]: item["downloadable_artifact"] for item in response.json()["files"]}
    assert files["model.litertlm"] is True
    assert files["weights.safetensors"] is True
    assert files["config.json"] is False
    assert files["run.py"] is False


def test_huggingface_download_rejects_path_traversal_before_network(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        response = client.post("/api/models/huggingface/download", json={
            "repo_id": "example/model", "filename": "../evil.litertlm",
        })
    assert response.status_code == 422


def test_huggingface_download_is_explicit_bounded_and_audited(monkeypatch, tmp_path):
    payload = b"verified fake litertlm artifact"
    monkeypatch.setattr(huggingface, "_hub_json", lambda url: {
        "id": "example/model",
        "siblings": [{"rfilename": "model.litertlm", "size": len(payload)}],
    })

    class FakeResponse:
        headers = {"Content-Length": str(len(payload))}

        def __init__(self):
            self.remaining = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size=-1):
            data, self.remaining = self.remaining, b""
            return data

    monkeypatch.setattr(huggingface, "_request", lambda *_args, **_kwargs: FakeResponse())
    with _client(monkeypatch, tmp_path) as client:
        response = client.post("/api/models/huggingface/download", json={
            "repo_id": "example/model", "filename": "model.litertlm", "revision": "main",
        })
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["downloaded"] is True
        assert data["inference_enabled"] is True
        artifact = tmp_path / "models" / "example--model" / "main" / "model.litertlm"
        assert artifact.read_bytes() == payload
        registered = client.post("/api/models/register", json={
            "model_id": "hf-test-model", "name": "Downloaded test model", "kind": "chat",
            "file_path": str(artifact), "format": "litertlm", "sha256": data["sha256"],
        })
    assert registered.status_code == 200, registered.text

def test_huggingface_download_rejects_insufficient_storage_before_network(monkeypatch, tmp_path):
    payload = b"x" * 1024
    monkeypatch.setattr(huggingface, "_hub_json", lambda url: {
        "id": "example/model", "siblings": [{"rfilename": "model.litertlm", "size": len(payload)}],
    })
    class Usage:
        total = 1024 * 1024
        used = 900 * 1024
        free = 124 * 1024
    monkeypatch.setattr(huggingface.shutil, "disk_usage", lambda _path: Usage())
    monkeypatch.setattr(huggingface, "_request", lambda *_args, **_kwargs: pytest.fail("must reject before network download"))
    with _client(monkeypatch, tmp_path) as client:
        response = client.post("/api/models/huggingface/download", json={
            "repo_id": "example/model", "filename": "model.litertlm", "revision": "main",
        })
    assert response.status_code == 507
    assert "Insufficient storage" in response.json()["detail"]


def test_huggingface_cached_artifact_still_obeys_current_size_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "huggingface_max_download_bytes", 8)
    monkeypatch.setattr(huggingface, "_hub_json", lambda url: {
        "id": "example/model",
        # Hub metadata can omit file size, so the local cache must enforce the cap too.
        "siblings": [{"rfilename": "model.litertlm"}],
    })
    cached = tmp_path / "models" / "example--model" / "main" / "model.litertlm"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"x" * 9)
    monkeypatch.setattr(
        huggingface,
        "_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cache hit must not download")),
    )

    with _client(monkeypatch, tmp_path) as client:
        response = client.post("/api/models/huggingface/download", json={
            "repo_id": "example/model", "filename": "model.litertlm", "revision": "main",
        })

    assert response.status_code == 413
    assert "Cached artifact exceeds" in response.json()["detail"]

def test_model_cache_inventory_is_bounded_read_only_and_ignores_partial_files(monkeypatch, tmp_path):
    root = tmp_path / "models"
    (root / "repo" / "revision").mkdir(parents=True)
    (root / "repo" / "revision" / "model.litertlm").write_bytes(b"abc123")
    (root / "repo" / "revision" / ".nova-download-partial").write_bytes(b"partial")
    monkeypatch.setattr(settings, "huggingface_cache_dir", root)
    with _client(monkeypatch, tmp_path) as client:
        response = client.get("/api/models/huggingface/cache")
    assert response.status_code == 200
    data = response.json()
    assert data["file_count"] == 1
    assert data["total_bytes"] == 6
    assert data["files"][0]["relative_path"] == "repo/revision/model.litertlm"
    assert "registered" not in data["files"][0]


def test_feature_switch_blocks_hub_search_and_download(monkeypatch, tmp_path):
    monkeypatch.setattr(huggingface, "_hub_json", lambda _url: pytest.fail("network metadata should not be requested"))
    with _client(monkeypatch, tmp_path) as client:
        response = client.put("/api/settings/features", json={
            "local_retrieval_enabled": True,
            "model_hub_enabled": False,
            "model_downloads_enabled": False,
            "whisper_enabled": True,
            "piper_enabled": True,
            "ocr_enabled": True,
            "onnx_runtime_enabled": True,
            "max_model_download_bytes": 100000000,
        })
        assert response.status_code == 200, response.text
        search = client.get("/api/models/huggingface/search?q=tiny")
        download = client.post("/api/models/huggingface/download", json={
            "repo_id": "example/model", "filename": "model.litertlm", "revision": "main",
        })
    assert search.status_code == 403
    assert download.status_code == 403


def test_huggingface_token_can_be_configured_and_cleared_without_echo(monkeypatch, tmp_path):
    import stat
    monkeypatch.delenv("NOVA_HUGGINGFACE_TOKEN", raising=False)
    monkeypatch.setattr(settings, "huggingface_token", "")
    secret = "hf_test_secret_value"
    with _client(monkeypatch, tmp_path) as client:
        saved = client.put("/api/models/huggingface/token", json={"token": secret})
        assert saved.status_code == 200, saved.text
        assert secret not in saved.text
        assert saved.json()["token_returned"] is False
        token_path = tmp_path / "private" / "huggingface.token"
        assert token_path.read_text().strip() == secret
        assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
        assert huggingface._token() == secret
        status = client.get("/api/models/huggingface/status")
        assert status.status_code == 200
        assert secret not in status.text
        cleared = client.delete("/api/models/huggingface/token")
        assert cleared.status_code == 200, cleared.text
        assert not token_path.exists()
        assert cleared.json()["token_returned"] is False
