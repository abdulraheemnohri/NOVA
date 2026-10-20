from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from nova import web_search


def test_build_google_url_uses_requested_mobile_google_parameters():
    url = web_search.build_google_search_url("NOVA local AI")
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "www.google.com"
    assert params["q"] == ["NOVA local AI"]
    assert params["client"] == ["ms-android-google"]
    assert params["udm"] == ["50"]


def test_parser_extracts_external_heading_links_and_ignores_google():
    parser = web_search._ResultParser()
    parser.feed(
        '<a href="https://example.org/article"><h3>Example Article</h3></a>'
        '<a href="https://www.google.com/search?q=internal"><h3>Google internal</h3></a>'
        '<a href="javascript:alert(1)"><h3>Unsafe link</h3></a>'
    )
    assert parser.results == [{"title": "Example Article", "url": "https://example.org/article"}]


def test_google_search_returns_results(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}
        encoding = "utf-8"
        content = b'<a href="https://example.org"><h3>Useful Result</h3></a>'

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def get(self, url):
            assert url.startswith("https://www.google.com/search?")
            return FakeResponse()

    monkeypatch.setattr(web_search.httpx, "Client", FakeClient)
    result = web_search.google_search("test query")
    assert result["status"] == "ok"
    assert result["results"] == [{"title": "Useful Result", "url": "https://example.org"}]


def test_google_search_falls_back_to_link_when_unavailable(monkeypatch):
    class FakeClient:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def get(self, url):
            raise httpx.ConnectError("offline")

    monkeypatch.setattr(web_search.httpx, "Client", FakeClient)
    result = web_search.google_search("offline test")
    assert result["status"] == "unavailable"
    assert result["results"] == []
    assert result["search_url"].startswith("https://www.google.com/search?")


@pytest.mark.parametrize("query", ["", " "])
def test_google_search_rejects_empty_query(query):
    with pytest.raises(ValueError):
        web_search.google_search(query)


def test_google_search_rejects_long_query():
    with pytest.raises(ValueError):
        web_search.google_search("x" * 401)
