from contextlib import contextmanager
from fastapi.testclient import TestClient

from nova.config import settings
from nova.main import app


@contextmanager
def _client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "api_token_file", tmp_path / "api.token")
    monkeypatch.setattr(settings, "workspace", tmp_path / "workspace")
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    settings.workspace.mkdir(parents=True, exist_ok=True)
    with TestClient(app) as client:
        token = settings.api_token_file.read_text(encoding="utf-8").strip()
        client.headers.update({"Authorization": f"Bearer {token}"})
        yield client


def test_model_catalog_includes_voice_and_low_end_profiles(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        response = client.get("/api/models/catalog")
    assert response.status_code == 200
    data = response.json()
    assert any(m["kind"] == "speech_to_text" for m in data["catalog"])
    assert any(m["kind"] == "text_to_speech" for m in data["catalog"])
    assert any(p["id"] == "low_end" for p in data["device_profiles"])
    assert "LiteRT-LM-only" in data["runtime_policy"]


def test_model_selection_persists_litert_model_locally(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        artifact = tmp_path / "qwen.litertlm"
        artifact.write_bytes(b"test model bytes")
        registered = client.post("/api/models/register", json={
            "model_id": "local-qwen", "name": "Local Qwen", "kind": "reasoning",
            "file_path": str(artifact), "format": "litertlm",
        })
        assert registered.status_code == 200, registered.text
        response = client.post("/api/models/select", json={"model_id": "local-qwen"})
        assert response.status_code == 200, response.text
        listed = client.get("/api/models")
    assert listed.status_code == 200
    assert listed.json()["active_model_id"] == "local-qwen"
    assert next(m for m in listed.json()["models"] if m.get("model_id") == "local-qwen")["active"]


def test_non_litert_model_cannot_be_selected_for_chat(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        response = client.post("/api/models/select", json={"model_id": "voice-piper-tts"})
    assert response.status_code == 400
    assert "no LiteRT-LM inference adapter" in response.json()["detail"]


def test_unknown_model_cannot_be_selected(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        response = client.post("/api/models/select", json={"model_id": "remote-cloud-model"})
    assert response.status_code == 404


def test_local_model_registration_checks_checksum(monkeypatch, tmp_path):
    artifact = tmp_path / "local.litertlm"
    artifact.write_bytes(b"fake model bytes")
    with _client(monkeypatch, tmp_path) as client:
        bad = client.post("/api/models/register", json={
            "model_id": "local-test", "name": "Test", "kind": "chat",
            "file_path": str(artifact), "format": "litertlm", "sha256": "0" * 64,
        })
        assert bad.status_code == 422
        good = client.post("/api/models/register", json={
            "model_id": "local-test", "name": "Test", "kind": "chat",
            "file_path": str(artifact), "format": "litertlm",
        })
        assert good.status_code == 200, good.text
        selected = client.post("/api/models/select", json={"model_id": "local-test"})
    assert selected.status_code == 200


def test_model_selection_refuses_changed_artifact_checksum(monkeypatch, tmp_path):
    artifact = tmp_path / "tampered.litertlm"
    artifact.write_bytes(b"original bytes")
    with _client(monkeypatch, tmp_path) as client:
        registered = client.post("/api/models/register", json={
            "model_id": "tampered-model", "name": "Tampered model", "kind": "chat",
            "file_path": str(artifact), "format": "litertlm",
        })
        assert registered.status_code == 200, registered.text
        artifact.write_bytes(b"changed after registration")
        response = client.post("/api/models/select", json={"model_id": "tampered-model"})
    assert response.status_code == 409
    assert "checksum changed" in response.json()["detail"]


def test_litert_registration_requires_expected_extension(monkeypatch, tmp_path):
    artifact = tmp_path / "model.bin"
    artifact.write_bytes(b"not a litertlm file")
    with _client(monkeypatch, tmp_path) as client:
        response = client.post("/api/models/register", json={
            "model_id": "wrong-extension", "name": "Wrong extension", "kind": "chat",
            "file_path": str(artifact), "format": "litertlm",
        })
    assert response.status_code == 422
    assert ".litertlm" in response.json()["detail"]


def test_model_activation_is_persisted_and_inactive_models_cannot_be_selected(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        artifact = tmp_path / "activation.litertlm"
        artifact.write_bytes(b"activation test model")
        registered = client.post("/api/models/register", json={
            "model_id": "activation-model", "name": "Activation model", "kind": "chat",
            "file_path": str(artifact), "format": "litertlm",
        })
        assert registered.status_code == 200, registered.text
        selected = client.post("/api/models/select", json={"model_id": "activation-model"})
        assert selected.status_code == 200, selected.text

        disabled = client.put("/api/models/activation", json={
            "model_id": "activation-model", "enabled": False,
        })
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["status"] == "inactive"
        assert disabled.json()["active_model_id"] == settings.litert_model

        listing = client.get("/api/models")
        item = next(m for m in listing.json()["models"] if m.get("model_id") == "activation-model")
        assert item["enabled"] is False
        assert item["active"] is False

        blocked = client.post("/api/models/select", json={"model_id": "activation-model"})
        assert blocked.status_code == 409
        assert "inactive" in blocked.json()["detail"]

        enabled = client.put("/api/models/activation", json={
            "model_id": "activation-model", "enabled": True,
        })
        assert enabled.status_code == 200
        assert enabled.json()["enabled"] is True
        selected_again = client.post("/api/models/select", json={"model_id": "activation-model"})
        assert selected_again.status_code == 200


def test_configured_fallback_model_cannot_be_deactivated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "litert_model", "litert-small-instruct")
    with _client(monkeypatch, tmp_path) as client:
        response = client.put("/api/models/activation", json={
            "model_id": "litert-small-instruct", "enabled": False,
        })
        assert response.status_code == 409
        assert "fallback cannot be disabled" in response.json()["detail"]


def test_unknown_model_activation_is_rejected(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        response = client.put("/api/models/activation", json={
            "model_id": "not-a-known-model", "enabled": False,
        })
        assert response.status_code == 404
