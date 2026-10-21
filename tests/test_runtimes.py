from contextlib import contextmanager
import subprocess
from unittest.mock import patch

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
    token_path.write_text("runtime-test-token")
    append_audit(settings.audit_path, "test.start", {})
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        yield client, {"Authorization": "Bearer runtime-test-token"}


def test_runtime_inventory_separates_chat_and_specialized_runtimes(tmp_path, monkeypatch):
    from nova import runtimes

    monkeypatch.setattr(runtimes, "litert_health", lambda: {
        "reachable": True, "base_url": "http://127.0.0.1:9379/v1"
    })
    monkeypatch.setattr(runtimes, "_resolve_executable", lambda configured, candidates: (
        "/usr/local/bin/whisper-cli" if candidates == ("whisper-cli",) else
        "/usr/local/bin/piper" if candidates == ("piper",) else None
    ))
    monkeypatch.setattr(runtimes, "_module_available", lambda name: name == "onnxruntime")
    with _client(tmp_path, monkeypatch) as (client, headers):
        response = client.get("/api/runtimes", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["primary_chat_runtime"] == "litert-lm"
        assert body["automatic_fallback"] is False
        entries = {item["id"]: item for item in body["runtimes"]}
        assert entries["litert-lm"]["status"] == "ready"
        assert entries["litert-lm"]["endpoint_reachable"] is True
        assert entries["litert-lm"]["model_load_state"] == "unknown"
        assert entries["litert-lm"]["configured_model_advertised"] is None
        assert entries["litert-lm"]["active_model_advertised"] is None
        assert entries["litert-lm"]["active_model_id"]
        assert "model load state is not reported" in entries["litert-lm"]["policy"]
        assert entries["whisper-cpp"]["detected"] is True
        assert entries["onnx-runtime"]["detected"] is True
        assert entries["llama-cpp"]["status"] == "not_available"


def test_whisper_transcription_uses_safe_argv_and_cleans_files(tmp_path, monkeypatch):
    from nova.config import settings
    from nova import runtimes

    model = tmp_path / "ggml-base.bin"
    model.write_bytes(b"test-model")
    monkeypatch.setattr(settings, "whisper_cli_path", "/usr/local/bin/whisper-cli")
    monkeypatch.setattr(settings, "whisper_model_path", model)
    monkeypatch.setattr(settings, "workspace", tmp_path / "workspace")
    monkeypatch.setattr(settings, "whisper_timeout_seconds", 60)
    monkeypatch.setattr(runtimes, "_resolve_executable", lambda configured, candidates: "/usr/local/bin/whisper-cli")

    observed = {}
    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        prefix = command[command.index("-of") + 1]
        with open(prefix + ".txt", "w", encoding="utf-8") as stream:
            stream.write("hello from offline whisper")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(runtimes.subprocess, "run", fake_run)
    wav = b"RIFF" + (4).to_bytes(4, "little") + b"WAVE" + b"audio-payload"
    with _client(tmp_path, monkeypatch) as (client, headers):
        response = client.post("/api/runtimes/whisper/transcribe", headers=headers,
                               files={"file": ("sample.wav", wav, "audio/wav")})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["runtime"] == "whisper.cpp"
        assert body["transcript"] == "hello from offline whisper"
        assert observed["kwargs"]["shell"] is False
        assert observed["kwargs"]["timeout"] == 60
        assert "-otxt" in observed["command"]
        assert not list((tmp_path / "workspace" / ".nova-audio").glob("*.wav"))
        assert not list((tmp_path / "workspace" / ".nova-audio").glob("*-transcript.txt"))


def test_whisper_rejects_non_wav_upload(tmp_path, monkeypatch):
    from nova.config import settings
    from nova import runtimes

    model = tmp_path / "ggml-base.bin"
    model.write_bytes(b"test-model")
    monkeypatch.setattr(settings, "whisper_cli_path", "/usr/local/bin/whisper-cli")
    monkeypatch.setattr(settings, "whisper_model_path", model)
    monkeypatch.setattr(runtimes, "_resolve_executable", lambda configured, candidates: "/usr/local/bin/whisper-cli")
    with _client(tmp_path, monkeypatch) as (client, headers):
        response = client.post("/api/runtimes/whisper/transcribe", headers=headers,
                               files={"file": ("sample.xyz", b"not audio", "application/octet-stream")})
        assert response.status_code == 415


def test_whisper_requires_configured_model(tmp_path, monkeypatch):
    from nova.config import settings
    from nova import runtimes

    monkeypatch.setattr(settings, "whisper_cli_path", "/usr/local/bin/whisper-cli")
    monkeypatch.setattr(settings, "whisper_model_path", tmp_path / "missing.bin")
    monkeypatch.setattr(runtimes, "_resolve_executable", lambda configured, candidates: "/usr/local/bin/whisper-cli")
    with _client(tmp_path, monkeypatch) as (client, headers):
        response = client.post("/api/runtimes/whisper/transcribe", headers=headers,
                               files={"file": ("sample.wav", b"RIFF0000WAVEaudio", "audio/wav")})
        assert response.status_code == 503


def test_piper_synthesis_uses_local_model_and_returns_audio(tmp_path, monkeypatch):
    from nova.config import settings
    from nova import runtimes

    model = tmp_path / "voice.onnx"
    model.write_bytes(b"test-model")
    (tmp_path / "voice.onnx.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(settings, "piper_cli_path", "/usr/local/bin/piper")
    monkeypatch.setattr(settings, "piper_model_path", model)
    monkeypatch.setattr(settings, "workspace", tmp_path / "workspace")
    monkeypatch.setattr(settings, "whisper_timeout_seconds", 60)
    monkeypatch.setattr(runtimes, "_resolve_executable", lambda configured, candidates: "/usr/local/bin/piper")

    observed = {}
    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        output = command[command.index("--output_file") + 1]
        with open(output, "wb") as stream:
            stream.write(b"RIFF" + (4).to_bytes(4, "little") + b"WAVE" + b"audio")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(runtimes.subprocess, "run", fake_run)
    with _client(tmp_path, monkeypatch) as (client, headers):
        response = client.post("/api/runtimes/piper/synthesize", headers=headers,
                               json={"text": "Hello from local TTS"})
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("audio/wav")
        assert response.content.startswith(b"RIFF")
        assert observed["kwargs"]["shell"] is False
        assert observed["kwargs"]["input"] == "Hello from local TTS"
        assert not list((tmp_path / "workspace" / ".nova-audio").glob("*-speech.wav"))


def test_piper_synthesis_requires_voice_metadata(tmp_path, monkeypatch):
    from nova.config import settings
    from nova import runtimes

    model = tmp_path / "voice.onnx"
    model.write_bytes(b"test-model")
    monkeypatch.setattr(settings, "piper_cli_path", "/usr/local/bin/piper")
    monkeypatch.setattr(settings, "piper_model_path", model)
    monkeypatch.setattr(runtimes, "_resolve_executable", lambda configured, candidates: "/usr/local/bin/piper")
    with _client(tmp_path, monkeypatch) as (client, headers):
        response = client.post("/api/runtimes/piper/synthesize", headers=headers,
                               json={"text": "hello"})
        assert response.status_code == 503


def test_ocr_rejects_unsupported_extension_before_runtime_lookup(tmp_path, monkeypatch):
    from nova import runtimes
    with _client(tmp_path, monkeypatch) as (client, headers):
        response = client.post("/api/runtimes/ocr/extract", headers=headers,
                               files={"file": ("scan.pdf", b"not-an-image", "application/pdf")})
        assert response.status_code == 415


def test_ocr_requires_local_tesseract(tmp_path, monkeypatch):
    from nova import runtimes
    monkeypatch.setattr(runtimes, "_resolve_executable", lambda configured, candidates: None)
    with _client(tmp_path, monkeypatch) as (client, headers):
        response = client.post("/api/runtimes/ocr/extract", headers=headers,
                               files={"file": ("scan.png", b"valid-size-placeholder", "image/png")})
        assert response.status_code == 503


def test_tesseract_ocr_uses_shell_free_argv_and_cleans_temporary_files(tmp_path, monkeypatch):
    import sys
    from types import ModuleType
    from pathlib import Path
    from nova.config import settings
    from nova import runtimes

    class FakeNormalized:
        def save(self, path, **kwargs):
            Path(path).write_bytes(b"normalized-png")
        def close(self):
            pass

    class FakeImage:
        format = "PNG"
        size = (32, 24)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def verify(self):
            pass
        def convert(self, mode):
            assert mode == "RGB"
            return FakeNormalized()

    pil = ModuleType("PIL")
    image_module = ModuleType("PIL.Image")
    image_module.open = lambda stream: FakeImage()
    pil.Image = image_module
    pil.UnidentifiedImageError = type("UnidentifiedImageError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "PIL", pil)
    monkeypatch.setitem(sys.modules, "PIL.Image", image_module)
    monkeypatch.setattr(runtimes, "_resolve_executable", lambda configured, candidates: "/usr/bin/tesseract")
    monkeypatch.setattr(settings, "workspace", tmp_path / "workspace")
    monkeypatch.setattr(settings, "ocr_timeout_seconds", 17)
    observed = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        assert Path(command[1]).is_file()
        return subprocess.CompletedProcess(command, 0, stdout="recognized local text", stderr="")

    monkeypatch.setattr(runtimes.subprocess, "run", fake_run)
    with _client(tmp_path, monkeypatch) as (client, headers):
        response = client.post("/api/runtimes/ocr/extract", headers=headers,
                               files={"file": ("scan.png", b"fake-image-bytes", "image/png")})
        assert response.status_code == 200, response.text
        assert response.json()["text"] == "recognized local text"
        assert observed["kwargs"]["shell"] is False
        assert observed["kwargs"]["timeout"] == 17
        assert observed["command"][0] == "/usr/bin/tesseract"
        assert not list((settings.workspace / ".nova-ocr").glob("ocr-*"))



def test_audio_conversion_uses_shell_free_ffmpeg_and_validates_output(tmp_path, monkeypatch):
    import subprocess
    from nova import runtimes

    source = tmp_path / "input.mp3"
    source.write_bytes(b"fake compressed audio")
    target = tmp_path / "normalized.wav"
    monkeypatch.setattr(runtimes.settings, "ffmpeg_cli_path", "/usr/bin/ffmpeg")
    monkeypatch.setattr(runtimes, "_resolve_executable", lambda configured, candidates: configured)
    captured = {}
    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        target.write_bytes(b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"\x00" * 16)
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(runtimes.subprocess, "run", fake_run)

    runtimes._convert_audio_to_wav(source, target, timeout=20)
    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["timeout"] == 20
    assert "-ac" in captured["argv"] and "1" in captured["argv"]
    assert "-ar" in captured["argv"] and "16000" in captured["argv"]


def test_audio_conversion_fails_closed_when_ffmpeg_missing(tmp_path, monkeypatch):
    import pytest
    from fastapi import HTTPException
    from nova import runtimes

    monkeypatch.setattr(runtimes.settings, "ffmpeg_cli_path", "")
    monkeypatch.setattr(runtimes, "_resolve_executable", lambda configured, candidates: None)
    with pytest.raises(HTTPException) as exc:
        runtimes._convert_audio_to_wav(tmp_path / "input.mp3", tmp_path / "output.wav", timeout=20)
    assert exc.value.status_code == 503

def test_distribution_version_lookup_is_read_only_and_skips_missing_packages(monkeypatch):
    from importlib.metadata import PackageNotFoundError
    from nova import runtimes

    calls = []

    def fake_version(name):
        calls.append(name)
        if name == "tflite-runtime":
            raise PackageNotFoundError(name)
        if name == "ai-edge-litert":
            return "1.2.3"
        raise AssertionError("unexpected package lookup")

    monkeypatch.setattr(runtimes.importlib.metadata, "version", fake_version)
    assert runtimes._distribution_version("tflite-runtime", "ai-edge-litert") == "1.2.3"
    assert calls == ["tflite-runtime", "ai-edge-litert"]


def test_runtime_preflight_is_read_only_and_keeps_litert_as_primary(tmp_path, monkeypatch):
    from nova import runtimes

    monkeypatch.setattr(runtimes, "litert_health", lambda: {
        "reachable": False, "base_url": "http://127.0.0.1:9379/v1"
    })
    monkeypatch.setattr(runtimes, "_resolve_executable", lambda configured, candidates: None)
    monkeypatch.setattr(runtimes, "_module_available", lambda name: False)
    with _client(tmp_path, monkeypatch) as (client, headers):
        response = client.get("/api/runtimes/preflight", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ready"] is False
        assert body["primary_chat_runtime"] == "litert-lm"
        assert body["automatic_fallback"] is False
        assert "does not install packages" in body["safety"]
        checks = {item["runtime_id"]: item for item in body["checks"]}
        assert checks["litert-lm"]["severity"] == "critical"
        assert "Start/configure" in checks["litert-lm"]["action"]
        assert checks["whisper-cpp"]["severity"] == "recommended"


def test_runtime_install_preview_is_allowlisted_and_never_executes(tmp_path, monkeypatch):
    from nova import runtimes

    def forbidden(*args, **kwargs):
        raise AssertionError("preview must not execute commands")

    monkeypatch.setattr(runtimes.subprocess, "run", forbidden)
    with _client(tmp_path, monkeypatch) as (client, headers):
        response = client.post("/api/runtimes/operations/preview", headers=headers,
                               json={"runtime_id": "ffmpeg-audio"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["packages"] == ["ffmpeg"]
        assert body["command"] == "sudo apt-get install --no-install-recommends ffmpeg"
        assert body["requires_operator_approval"] is True
        assert body["executed"] is False

        rejected = client.post("/api/runtimes/operations/preview", headers=headers,
                               json={"runtime_id": "custom; rm -rf /"})
        assert rejected.status_code == 422



def test_runtime_install_request_requires_explicit_decision_and_never_executes(tmp_path, monkeypatch):
    from nova import runtimes

    def forbidden(*args, **kwargs):
        raise AssertionError("approval workflow must never execute a package manager")

    monkeypatch.setattr(runtimes.subprocess, "run", forbidden)
    with _client(tmp_path, monkeypatch) as (client, headers):
        created = client.post("/api/runtimes/operations/requests", headers=headers,
                              json={"runtime_id": "ffmpeg-audio"})
        assert created.status_code == 201, created.text
        request = created.json()
        assert request["status"] == "pending"
        assert request["packages"] == ["ffmpeg"]
        assert request["executed"] is False

        listed = client.get("/api/runtimes/operations/requests", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["requests"][0]["request_id"] == request["request_id"]

        approved = client.post(
            f"/api/runtimes/operations/requests/{request['request_id']}/decision",
            headers=headers, json={"decision": "approve", "note": "Reviewed locally"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
        assert approved.json()["executed"] is False

        duplicate = client.post(
            f"/api/runtimes/operations/requests/{request['request_id']}/decision",
            headers=headers, json={"decision": "reject"},
        )
        assert duplicate.status_code == 409

        missing = client.post(
            "/api/runtimes/operations/requests/missing/decision",
            headers=headers, json={"decision": "approve"},
        )
        assert missing.status_code == 404

        unsupported = client.post("/api/runtimes/operations/requests", headers=headers,
                                  json={"runtime_id": "custom; rm -rf /"})
        assert unsupported.status_code == 422


def test_runtime_install_request_can_be_rejected(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, headers):
        created = client.post("/api/runtimes/operations/requests", headers=headers,
                              json={"runtime_id": "tesseract-ocr"})
        assert created.status_code == 201
        request_id = created.json()["request_id"]
        rejected = client.post(
            f"/api/runtimes/operations/requests/{request_id}/decision",
            headers=headers, json={"decision": "reject", "note": "Not needed"},
        )
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "rejected"
        assert rejected.json()["decision_note"] == "Not needed"


def test_runtime_install_execution_is_never_supported_even_when_env_enabled(tmp_path, monkeypatch):
    from nova import runtimes

    monkeypatch.setenv("NOVA_RUNTIME_INSTALL_EXECUTION_ENABLED", "true")
    monkeypatch.setattr(
        runtimes.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("NOVA must never run package managers")),
    )
    with _client(tmp_path, monkeypatch) as (client, headers):
        created = client.post(
            "/api/runtimes/operations/requests",
            headers=headers,
            json={"runtime_id": "ffmpeg-audio"},
        )
        request_id = created.json()["request_id"]
        client.post(
            f"/api/runtimes/operations/requests/{request_id}/decision",
            headers=headers,
            json={"decision": "approve"},
        )
        response = client.post(
            f"/api/runtimes/operations/requests/{request_id}/execute",
            headers=headers,
            json={"confirm_request_id": request_id, "confirm_install": True},
        )
        assert response.status_code == 403
        assert "never runs package managers" in response.json()["detail"]

def test_runtime_install_executor_is_blocked_regardless_of_root_or_approval(tmp_path, monkeypatch):
    from nova import runtimes

    monkeypatch.setenv("NOVA_RUNTIME_INSTALL_EXECUTION_ENABLED", "true")
    monkeypatch.setattr(runtimes.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        runtimes.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("NOVA must never run package managers")),
    )
    with _client(tmp_path, monkeypatch) as (client, headers):
        created = client.post(
            "/api/runtimes/operations/requests",
            headers=headers,
            json={"runtime_id": "ffmpeg-audio"},
        )
        assert created.status_code == 201
        request_id = created.json()["request_id"]

        # Execution remains blocked before approval, even for a root backend.
        response = client.post(
            f"/api/runtimes/operations/requests/{request_id}/execute",
            headers=headers,
            json={"confirm_request_id": request_id, "confirm_install": True},
        )
        assert response.status_code == 403

        approved = client.post(
            f"/api/runtimes/operations/requests/{request_id}/decision",
            headers=headers,
            json={"decision": "approve"},
        )
        assert approved.status_code == 200

        # Approval is audit metadata only; it never authorizes execution.
        response = client.post(
            f"/api/runtimes/operations/requests/{request_id}/execute",
            headers=headers,
            json={"confirm_request_id": request_id, "confirm_install": True},
        )
        assert response.status_code == 403
        assert "never runs package managers" in response.json()["detail"]


def test_runtime_feature_switches_block_optional_capabilities(tmp_path, monkeypatch):
    from nova import runtimes
    from nova.config import settings

    monkeypatch.setattr(settings, "litert_lm_command", "")
    with _client(tmp_path, monkeypatch) as (client, headers):
        response = client.put("/api/settings/features", headers=headers, json={
            "local_retrieval_enabled": True,
            "model_hub_enabled": True,
            "model_downloads_enabled": True,
            "whisper_enabled": False,
            "piper_enabled": False,
            "ocr_enabled": False,
            "onnx_runtime_enabled": False,
            "max_model_download_bytes": 100000000,
        })
        assert response.status_code == 200, response.text
        whisper = client.post("/api/runtimes/whisper/transcribe", headers=headers,
                              files={"file": ("sample.wav", b"not audio", "audio/wav")})
        ocr = client.post("/api/runtimes/ocr/extract", headers=headers,
                          files={"file": ("sample.png", b"not image", "image/png")})
        piper = client.post("/api/runtimes/piper/synthesize", headers=headers,
                            json={"text": "hello"})
    assert whisper.status_code == 403
    assert ocr.status_code == 403
    assert piper.status_code == 403


def test_litert_autostart_status_is_read_only_and_reports_capability(tmp_path, monkeypatch):
    from nova import runtimes
    monkeypatch.setattr(runtimes.platform, "system", lambda: "Windows")
    with _client(tmp_path, monkeypatch) as (client, headers):
        response = client.get("/api/runtimes/litert/autostart", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["supported"] is False
    assert data["service"] == "nova-litert-lm.service"



def test_runtime_inventory_reports_configured_model_advertisement_without_claiming_loaded(tmp_path, monkeypatch):
    from nova import runtimes
    from nova.config import settings

    monkeypatch.setattr(settings, "litert_model", "nova-model")
    monkeypatch.setattr(runtimes, "active_model_id", lambda: "nova-model")
    monkeypatch.setattr(runtimes, "litert_health", lambda: {
        "reachable": True,
        "base_url": "http://127.0.0.1:9379/v1",
        "advertised_model_ids": ["nova-model", "other-model"],
    })
    monkeypatch.setattr(runtimes, "_resolve_executable", lambda configured, candidates: None)
    monkeypatch.setattr(runtimes, "_module_available", lambda name: False)

    inventory = runtimes.runtime_inventory()
    entry = next(item for item in inventory["runtimes"] if item["id"] == "litert-lm")
    assert entry["configured_model_advertised"] is True
    assert entry["active_model_id"] == "nova-model"
    assert entry["active_model_advertised"] is True
    assert entry["model_load_state"] == "unknown"

    monkeypatch.setattr(runtimes, "litert_health", lambda: {
        "reachable": True,
        "base_url": "http://127.0.0.1:9379/v1",
        "advertised_model_ids": ["other-model"],
    })
    inventory = runtimes.runtime_inventory()
    entry = next(item for item in inventory["runtimes"] if item["id"] == "litert-lm")
    assert entry["configured_model_advertised"] is False
    assert entry["active_model_advertised"] is False
    assert entry["model_load_state"] == "unknown"
