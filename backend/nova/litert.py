"""Loopback-only adapter for a verified LiteRT-LM OpenAI-compatible server."""
import ipaddress, json
from urllib.error import URLError, HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from nova.config import settings

class LiteRTError(RuntimeError): pass

def _base() -> str:
    parsed=urlparse(settings.litert_base_url)
    if parsed.scheme != "http" or not parsed.hostname: raise LiteRTError("Endpoint must be HTTP on loopback.")
    try: address=ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        if parsed.hostname != "localhost": raise LiteRTError("Only loopback hosts are allowed.") from exc
    else:
        if not address.is_loopback: raise LiteRTError("External model endpoints are forbidden.")
    return settings.litert_base_url.rstrip("/")

def health() -> dict:
    base=_base()
    try:
        with urlopen(Request(base+"/models"), timeout=2) as response:
            return {"reachable": True, "base_url": base, "models_response": json.loads(response.read())}
    except (URLError, HTTPError, TimeoutError, ValueError, OSError):
        return {"reachable": False, "base_url": base, "message":"LiteRT-LM endpoint unavailable/incompatible; no fallback."}

def chat(message: str, max_tokens: int=512) -> str:
    base=_base()
    body=json.dumps({"model":settings.litert_model,"messages":[{"role":"user","content":message}],
                     "max_tokens":max(1,min(max_tokens,4096)),"temperature":0.2}).encode()
    req=Request(base+"/chat/completions",data=body,headers={"Content-Type":"application/json"},method="POST")
    try:
        with urlopen(req,timeout=120) as response: data=json.loads(response.read())
        return data["choices"][0]["message"]["content"]
    except (URLError, HTTPError, TimeoutError, ValueError, OSError, KeyError, IndexError, TypeError) as exc:
        raise LiteRTError("Local LiteRT-LM inference failed; verify runtime, model ID, and endpoint support.") from exc
