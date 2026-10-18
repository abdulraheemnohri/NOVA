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
