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
