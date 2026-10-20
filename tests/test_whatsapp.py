import asyncio
import json
import os

import httpx
import pytest

from nova.whatsapp import API_BASE, WhatsAppAgentPlatform


def test_status_never_exposes_api_key(tmp_path):
    service = WhatsAppAgentPlatform(tmp_path, _reply)
    asyncio.run(service.configure({"api_key": "secret-test-key", "enabled": False}))
    status = service.status()
    assert status["configured"] is True
    assert "secret-test-key" not in json.dumps(status)
    assert status["mode"] == "text-only"
    assert status["model_name"] == "Gemma 4-E4B (LiteRT-LM only)"


def test_config_rejects_unknown_fields_and_invalid_types(tmp_path):
    service = WhatsAppAgentPlatform(tmp_path, _reply)
    with pytest.raises(ValueError):
        asyncio.run(service.configure({"unexpected": True}))
    with pytest.raises(ValueError):
        asyncio.run(service.configure({"enabled": "yes"}))


def test_config_requires_key_before_enable(tmp_path):
    service = WhatsAppAgentPlatform(tmp_path, _reply)
    with pytest.raises(ValueError):
        asyncio.run(service.configure({"enabled": True}))


def test_secret_file_has_restrictive_permissions(tmp_path):
    service = WhatsAppAgentPlatform(tmp_path, _reply)
    asyncio.run(service.configure({"api_key": "secret-test-key"}))
    path = tmp_path / "whatsapp_agent_platform.json"
    assert path.exists()
    assert os.stat(path).st_mode & 0o077 == 0
    assert os.stat(tmp_path).st_mode & 0o077 == 0


def test_test_connection_does_not_advance_offset(tmp_path):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "object": "whatsapp_agent_platform", "next_offset": 22,
            "entry": [{"changes": [{"field": "messages", "value": {"messages": []}}]}],
        })
    service = WhatsAppAgentPlatform(
        tmp_path, _reply, base_url=API_BASE, transport=httpx.MockTransport(handler)
    )
    asyncio.run(service.configure({"api_key": "test-key"}))
    service._state["next_offset"] = 7
    result = asyncio.run(service.test_connection())
    assert result["ok"] is True
    assert service._state["next_offset"] == 7


def test_api_key_rejection_does_not_leak_response_body(tmp_path):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="secret body")
    service = WhatsAppAgentPlatform(
        tmp_path, _reply, transport=httpx.MockTransport(handler)
    )
    asyncio.run(service.configure({"api_key": "test-key"}))
    with pytest.raises(PermissionError) as exc:
        asyncio.run(service._get_updates(timeout=0))
    assert "secret body" not in str(exc.value)


def test_message_extractor_ignores_malformed_entries():
    payload = {"entry": [None, {"changes": [{"field": "other"}, {
        "field": "messages", "value": {"messages": [{"id": "1"}, None]}
    }]}]}
    assert WhatsAppAgentPlatform._messages(payload) == [{"id": "1"}]


def test_manual_send_requires_verified_creator(tmp_path):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    service = WhatsAppAgentPlatform(
        tmp_path, _reply, transport=httpx.MockTransport(handler)
    )
    asyncio.run(service.configure({"api_key": "test-key", "creator_id": "creator-123", "enabled": True}))
    with pytest.raises(PermissionError):
        asyncio.run(service.send_manual({"recipient": "other-user", "message": "hello"}))
    asyncio.run(service.stop())


async def _reply(message: str) -> str:
    return "reply:" + message


def test_enabled_requires_explicit_creator_allowlist(tmp_path):
    service = WhatsAppAgentPlatform(tmp_path, _reply)
    with pytest.raises(ValueError, match="creator WhatsApp user ID"):
        asyncio.run(service.configure({"api_key": "test-key", "enabled": True}))


def test_creator_id_is_saved_and_validated(tmp_path):
    service = WhatsAppAgentPlatform(tmp_path, _reply)
    status = asyncio.run(service.configure({"api_key": "test-key", "creator_id": "creator-123"}))
    assert status["creator_id"] == "creator-123"
    with pytest.raises(ValueError):
        asyncio.run(service.configure({"creator_id": "bad id"}))
