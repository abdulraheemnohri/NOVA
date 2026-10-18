from nova.whatsapp import endpoint,NOTICE
def test_endpoint_requires_https_and_blocks_private_hosts():
 assert endpoint("https://agent.example.com/api").scheme=="https"
 for u in ["http://agent.example.com","https://localhost/api","https://127.0.0.1/api","https://user:pass@agent.example.com"]:
  try:endpoint(u)
  except ValueError:pass
  else:raise AssertionError("unsafe endpoint accepted")
def test_notice_discloses_non_end_to_end_encryption():
 assert "not consider these chats end-to-end encrypted" in NOTICE

def test_webhook_body_reader_accepts_payload_within_limit():
 import asyncio
 from starlette.requests import Request
 from nova.whatsapp import read_webhook_body

 chunks = [b'{"object":', b'"whatsapp_business_account"}']
 async def receive():
  if chunks:
   return {"type": "http.request", "body": chunks.pop(0), "more_body": bool(chunks)}
  return {"type": "http.disconnect"}
 request = Request({"type": "http", "method": "POST", "path": "/api/whatsapp/webhook", "headers": []}, receive)
 assert asyncio.run(read_webhook_body(request, max_bytes=100)) == b'{"object":"whatsapp_business_account"}'


def test_webhook_body_reader_rejects_oversized_payload():
 import asyncio
 import pytest
 from fastapi import HTTPException
 from starlette.requests import Request
 from nova.whatsapp import read_webhook_body

 chunks = [b"12345", b"67890"]
 async def receive():
  if chunks:
   return {"type": "http.request", "body": chunks.pop(0), "more_body": bool(chunks)}
  return {"type": "http.disconnect"}
 request = Request({"type": "http", "method": "POST", "path": "/api/whatsapp/webhook", "headers": []}, receive)
 with pytest.raises(HTTPException) as exc:
  asyncio.run(read_webhook_body(request, max_bytes=8))
 assert exc.value.status_code == 413
