"""Loopback-only adapter for a verified LiteRT-LM OpenAI-compatible server.

Responses are bounded and redirects are rejected so a local endpoint cannot redirect
requests to a remote host or exhaust memory with an oversized payload.
"""
from __future__ import annotations

import ipaddress
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from nova.config import settings

MAX_HEALTH_RESPONSE_BYTES = 1_000_000
MAX_CHAT_RESPONSE_BYTES = 8_000_000


class LiteRTError(RuntimeError):
    """Raised when the explicitly configured local inference endpoint is unusable."""


class _RejectRedirects(HTTPRedirectHandler):
    """Do not follow redirects from the local inference server."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _base() -> str:
    parsed = urlparse(settings.litert_base_url)
    if parsed.scheme != "http" or not parsed.hostname:
        raise LiteRTError("Endpoint must be HTTP on loopback.")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        if parsed.hostname != "localhost":
            raise LiteRTError("Only loopback hosts are allowed.") from exc
    else:
        if not address.is_loopback:
            raise LiteRTError("External model endpoints are forbidden.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise LiteRTError("Endpoint URL must not contain credentials, query, or fragment.")
    return settings.litert_base_url.rstrip("/")


def _read_bounded(response, limit: int) -> bytes:
    """Read at most limit bytes plus one sentinel byte to detect oversize responses."""
    payload = response.read(limit + 1)
    if len(payload) > limit:
        raise LiteRTError("Local inference endpoint returned an oversized response.")
    return payload


def _open(request: Request, timeout: int):
    # urllib's default opener follows redirects. Never permit a loopback server to
    # redirect this process to an external URL.
    return build_opener(_RejectRedirects()).open(request, timeout=timeout)


def health() -> dict:
    base = _base()
    try:
        with _open(Request(base + "/models"), timeout=2) as response:
            payload = json.loads(_read_bounded(response, MAX_HEALTH_RESPONSE_BYTES))
            return {"reachable": True, "base_url": base, "models_response": payload}
    except (URLError, HTTPError, TimeoutError, ValueError, OSError, LiteRTError):
        return {
            "reachable": False,
            "base_url": base,
            "message": "LiteRT-LM endpoint unavailable/incompatible; no fallback.",
        }


def chat(message: str, max_tokens: int = 512, model_id: str | None = None, temperature: float = 0.2) -> str:
    base = _base()
    body = json.dumps(
        {
            "model": model_id or settings.litert_model,
            "messages": [{"role": "user", "content": message}],
            "max_tokens": max(1, min(max_tokens, 4096)),
            "temperature": max(0.0, min(float(temperature), 1.5)),
        }
    ).encode()
    request = Request(
        base + "/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _open(request, timeout=120) as response:
            data = json.loads(_read_bounded(response, MAX_CHAT_RESPONSE_BYTES))
        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise TypeError("Model response content is not text.")
        return content
    except (URLError, HTTPError, TimeoutError, ValueError, OSError, KeyError, IndexError, TypeError, LiteRTError) as exc:
        raise LiteRTError(
            "Local LiteRT-LM inference failed; verify runtime, model ID, and endpoint support."
        ) from exc
