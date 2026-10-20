from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from nova import duckduckgo_search as ddg
from nova.online_tools import list_online_tools


def test_direct_search_url_encodes_query():
    url = ddg.build_search_url("NOVA + Gemma")
    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "duckduckgo.com"
    assert parsed.path == "/"
    assert parse_qs(parsed.query)["q"] == ["NOVA + Gemma"]


def test_parser_extracts_result_links_and_rejects_unsafe_or_internal_urls():
    parser = ddg._ResultParser()
    parser.feed(
        '<a class="result__a" href="https://example.org/a">Example <b>article</b></a>'
        '<a class="result__a" href="javascript:alert(1)">Unsafe</a>'
        '<a class="result__a" href="https://duckduckgo.com/about">Internal</a>'
    )
    assert parser.results == [{"title": "Example article", "url": "https://example.org/a"}]


def test_search_returns_results(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}
        encoding = "utf-8"
        content = b'<a class="result__a" href="https://example.org">Useful result</a>'

    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def get(self, url, params):
            assert url == ddg.HTML_URL
            assert params == {"q": "test query"}
            return FakeResponse()

    monkeypatch.setattr(ddg.httpx, "Client", FakeClient)
    result = ddg.duckduckgo_search("test query")
    assert result["status"] == "ok"
    assert result["results"] == [{"title": "Useful result", "url": "https://example.org"}]


def test_search_falls_back_to_direct_link_when_offline(monkeypatch):
    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def get(self, *args, **kwargs): raise httpx.ConnectError("offline")

    monkeypatch.setattr(ddg.httpx, "Client", FakeClient)
    result = ddg.duckduckgo_search("offline")
    assert result["status"] == "unavailable"
    assert result["results"] == []
    assert result["search_url"].startswith("https://duckduckgo.com/?")


@pytest.mark.parametrize("query", ["", " "])
def test_search_rejects_empty_query(query):
    with pytest.raises(ValueError):
        ddg.duckduckgo_search(query)


def test_search_rejects_long_query():
    with pytest.raises(ValueError):
        ddg.duckduckgo_search("x" * 401)


def test_online_tools_catalog_has_duck_ai_and_search():
    data = list_online_tools()
    ids = {item["id"] for item in data["tools"]}
    assert "duck-ai" in ids
    assert "duckduckgo-search" in ids
    assert {"deepseek", "qwen-chat", "mistral-le-chat", "meta-ai", "poe"}.issubset(ids)
    assert data["mode"] == "browser_only"
    assert data["provider_api_calls"] is False
    assert data["api_keys_required"] is False
    assert data["automatic_prompt_forwarding"] is False
    assert data["count"] == len(data["tools"])
    assert "does not silently send" in data["notice"]
