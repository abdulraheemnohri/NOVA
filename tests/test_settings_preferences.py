from pydantic import ValidationError
import pytest

from nova.audit import verify_audit
from nova.config import settings
from nova.settings_preferences import (
    DEFAULT_PREFERENCES,
    PreferencesUpdate,
    get_preferences,
    update_preferences,
)


def test_preferences_defaults_and_persistence_are_stable(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")

    assert get_preferences() == DEFAULT_PREFERENCES

    updated = update_preferences(PreferencesUpdate(
        chat_max_tokens=2048,
        chat_temperature=0.7,
        auto_refresh_seconds=30,
        confirm_model_selection=False,
    ))
    assert updated == {
        "chat_max_tokens": 2048,
        "chat_temperature": 0.7,
        "auto_refresh_seconds": 30,
        "confirm_model_selection": False,
    }
    # A fresh read must reflect the persisted SQLite values.
    assert get_preferences() == updated
    valid, event_count = verify_audit(settings.audit_path)
    assert valid is True
    assert event_count == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"chat_max_tokens": 63},
        {"chat_max_tokens": 4097},
        {"chat_temperature": -0.01},
        {"chat_temperature": 1.51},
        {"auto_refresh_seconds": -1},
        {"auto_refresh_seconds": 301},
        {"unknown_setting": True},
    ],
)
def test_preferences_reject_out_of_range_or_unknown_values(payload):
    with pytest.raises(ValidationError):
        PreferencesUpdate(**payload)


def test_preferences_accept_inclusive_boundaries():
    value = PreferencesUpdate(
        chat_max_tokens=64,
        chat_temperature=0.0,
        auto_refresh_seconds=300,
        confirm_model_selection=True,
    )
    assert value.chat_max_tokens == 64
    assert value.chat_temperature == 0.0
    assert value.auto_refresh_seconds == 300


def test_feature_settings_persist_and_audit(tmp_path, monkeypatch):
    from nova.settings_preferences import (
        FeatureSettingsUpdate, DEFAULT_FEATURES, get_feature_settings, update_feature_settings,
    )
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")
    assert get_feature_settings() == DEFAULT_FEATURES
    updated = update_feature_settings(FeatureSettingsUpdate(
        local_retrieval_enabled=False,
        model_hub_enabled=False,
        model_downloads_enabled=False,
        whisper_enabled=False,
        piper_enabled=True,
        ocr_enabled=False,
        onnx_runtime_enabled=False,
        max_model_download_bytes=50_000_000,
    ))
    assert updated["local_retrieval_enabled"] is False
    assert updated["model_hub_enabled"] is False
    assert updated["model_downloads_enabled"] is False
    assert updated["whisper_enabled"] is False
    assert updated["piper_enabled"] is True
    assert updated["ocr_enabled"] is False
    assert updated["onnx_runtime_enabled"] is False
    assert updated["max_model_download_bytes"] == 50_000_000
    assert get_feature_settings() == updated
    valid, count = verify_audit(settings.audit_path)
    assert valid is True
    assert count == 1


def test_feature_settings_reject_unknown_fields_and_bad_download_limit():
    from nova.settings_preferences import FeatureSettingsUpdate
    with pytest.raises(ValidationError):
        FeatureSettingsUpdate(unknown_toggle=True)
    with pytest.raises(ValidationError):
        FeatureSettingsUpdate(max_model_download_bytes=0)
