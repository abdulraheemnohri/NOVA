from __future__ import annotations

import io

import pytest

from nova.config import settings
from nova.litert import LiteRTError, _base, _read_bounded


def test_base_accepts_ipv4_loopback(monkeypatch):
    monkeypatch.setattr(settings, "litert_base_url", "http://127.0.0.1:9379/v1")
    assert _base() == "http://127.0.0.1:9379/v1"


def test_base_accepts_localhost(monkeypatch):
    monkeypatch.setattr(settings, "litert_base_url", "http://localhost:9379/v1")
    assert _base() == "http://localhost:9379/v1"


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:9379/v1",
        "http://192.0.2.10:9379/v1",
        "http://example.com:9379/v1",
        "http://user:password@127.0.0.1:9379/v1",
        "http://127.0.0.1:9379/v1?token=secret",
    ],
)
def test_base_rejects_non_loopback_or_ambiguous_urls(monkeypatch, url):
    monkeypatch.setattr(settings, "litert_base_url", url)
    with pytest.raises(LiteRTError):
        _base()


def test_bounded_reader_accepts_payload_within_limit():
    assert _read_bounded(io.BytesIO(b"1234"), 4) == b"1234"


def test_bounded_reader_rejects_oversized_payload():
    with pytest.raises(LiteRTError, match="oversized"):
        _read_bounded(io.BytesIO(b"12345"), 4)


def test_redirect_handler_refuses_redirects():
    from urllib.request import Request
    from nova.litert import _RejectRedirects

    handler = _RejectRedirects()
    assert handler.redirect_request(
        Request("http://127.0.0.1:9379/v1/models"),
        io.BytesIO(b""),
        302,
        "Found",
        {},
        "https://example.com/collect",
    ) is None

class _HealthResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        import json
        return json.dumps(self.payload).encode("utf-8")


def test_health_requires_openai_compatible_models_list(monkeypatch):
    from nova import litert

    monkeypatch.setattr(settings, "litert_base_url", "http://127.0.0.1:9379/v1")
    monkeypatch.setattr(litert, "_open", lambda *_args, **_kwargs: _HealthResponse({
        "data": [{"id": "local-model"}]
    }))
    result = litert.health()
    assert result["reachable"] is True
    assert result["advertised_model_ids"] == ["local-model"]


@pytest.mark.parametrize("payload", [
    {"status": "ok"},
    {"data": "local-model"},
    {"data": [{}]},
    {"data": [{"id": 123}]},
])
def test_health_rejects_incompatible_models_response(monkeypatch, payload):
    from nova import litert

    monkeypatch.setattr(settings, "litert_base_url", "http://127.0.0.1:9379/v1")
    monkeypatch.setattr(litert, "_open", lambda *_args, **_kwargs: _HealthResponse(payload))
    result = litert.health()
    assert result["reachable"] is False
    assert "incompatible" in result["message"]
