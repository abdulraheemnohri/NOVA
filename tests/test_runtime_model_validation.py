from __future__ import annotations

import json
from pathlib import Path

from nova.runtimes import _validate_piper_voice, _validate_whisper_model


def test_whisper_model_validation_rejects_missing_and_tiny_files(tmp_path: Path) -> None:
    missing = _validate_whisper_model(tmp_path / "missing.bin")
    assert missing == {"valid": False, "reason": "model_file_missing", "size_bytes": 0}

    tiny = tmp_path / "tiny.bin"
    tiny.write_bytes(b"not a model")
    result = _validate_whisper_model(tiny)
    assert result["valid"] is False
    assert result["reason"] == "model_file_too_small"


def test_whisper_model_validation_accepts_plausible_local_asset(tmp_path: Path) -> None:
    model = tmp_path / "ggml-base.bin"
    model.write_bytes(b"ggml" + b"0" * 1_000_000)

    result = _validate_whisper_model(model)

    assert result["valid"] is True
    assert result["size_bytes"] > 1_000_000


def test_piper_validation_requires_model_and_valid_metadata(tmp_path: Path) -> None:
    model = tmp_path / "voice.onnx"
    sidecar = tmp_path / "voice.onnx.json"
    model.write_bytes(b"0" * 1_000_001)

    assert _validate_piper_voice(model, sidecar)["reason"] == "voice_metadata_missing"

    sidecar.write_text(json.dumps({
        "audio": {"sample_rate": 22050},
        "phoneme_id_map": {" ": [0], "a": [1]},
    }), encoding="utf-8")
    result = _validate_piper_voice(model, sidecar)

    assert result["valid"] is True
    assert result["sample_rate"] == 22050


def test_piper_validation_rejects_malformed_metadata(tmp_path: Path) -> None:
    model = tmp_path / "voice.onnx"
    sidecar = tmp_path / "voice.onnx.json"
    model.write_bytes(b"0" * 1_000_001)
    sidecar.write_text("{broken", encoding="utf-8")

    result = _validate_piper_voice(model, sidecar)

    assert result["valid"] is False
    assert result["reason"] == "voice_metadata_unreadable"
