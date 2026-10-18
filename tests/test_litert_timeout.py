import json

import pytest
from pydantic import ValidationError

from nova import litert
from nova.config import Settings, settings


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return json.dumps({
            "choices": [{"message": {"content": "NOVA_TIMEOUT_OK"}}]
        }).encode("utf-8")


def test_chat_uses_configured_bounded_timeout(monkeypatch):
    seen = {}

    def fake_open(request, timeout):
        seen["request"] = request
        seen["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(litert, "_base", lambda: "http://127.0.0.1:9379/v1")
    monkeypatch.setattr(litert, "_open", fake_open)
    monkeypatch.setattr(settings, "litert_chat_timeout_seconds", 45)

    assert litert.chat("test", max_tokens=64) == "NOVA_TIMEOUT_OK"
    assert seen["timeout"] == 45
    payload = json.loads(seen["request"].data.decode("utf-8"))
    assert payload["max_tokens"] == 64


@pytest.mark.parametrize("timeout", [4, 601])
def test_chat_timeout_setting_rejects_out_of_range_values(timeout):
    with pytest.raises(ValidationError):
        Settings(litert_chat_timeout_seconds=timeout)
