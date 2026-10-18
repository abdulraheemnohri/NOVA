from contextlib import contextmanager

from fastapi.testclient import TestClient

from nova.config import settings
from nova.main import app
from nova import huggingface


@contextmanager
def _client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "api_token_file", tmp_path / "api.token")
    monkeypatch.setattr(settings, "workspace", tmp_path / "workspace")
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    monkeypatch.setattr(settings, "huggingface_cache_dir", tmp_path / "models")
    settings.workspace.mkdir(parents=True, exist_ok=True)
    with TestClient(app) as client:
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
