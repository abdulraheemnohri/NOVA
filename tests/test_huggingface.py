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
    body = response.text
    assert "secret-test-token" not in body
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
