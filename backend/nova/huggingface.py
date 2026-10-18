"""Explicit, bounded Hugging Face Hub discovery and local artifact downloads.

Downloaded files are never executed. NOVA chat inference remains LiteRT-LM-only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from nova.config import settings
from nova.audit import append_audit
from nova.settings_preferences import get_feature_settings

router = APIRouter(prefix="/api/models/huggingface", tags=["Hugging Face model hub"])
_REPO_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_ALLOWED_ARTIFACTS = {".litertlm", ".gguf", ".tflite", ".onnx", ".safetensors"}
_MAX_QUERY = 120
_DEFAULT_LIMIT = 10
_MAX_LIMIT = 20
_CHUNK = 1024 * 1024


class DownloadRequest(BaseModel):
    repo_id: str = Field(min_length=3, max_length=200)
    filename: str = Field(min_length=1, max_length=500)
    revision: str = Field(default="main", min_length=1, max_length=120)
    max_bytes: int | None = Field(default=None, ge=1, le=2_000_000_000)


def _stored_token() -> str:
    """Read the operator-configured token from its private local file."""
    path = settings.huggingface_token_file.expanduser()
    try:
        if path.is_symlink() or not path.is_file():
            return ""
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _token() -> str:
    # Explicit environment configuration takes precedence; secrets are never returned.
    return (settings.huggingface_token or os.environ.get("NOVA_HUGGINGFACE_TOKEN", "") or _stored_token()).strip()


class HubTokenRequest(BaseModel):
    token: str = Field(min_length=1, max_length=4096)


@router.put("/token")
def configure_huggingface_token(req: HubTokenRequest):
    """Persist an operator-supplied Hub token in a private local file; never echo it."""
    token = req.token.strip()
    if not token or any(ord(ch) < 32 for ch in token):
        raise HTTPException(422, "Token must be non-empty and contain no control characters.")
    path = settings.huggingface_token_file.expanduser()
    if path.is_symlink():
        raise HTTPException(403, "Refusing to write a token through a symbolic link.")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".nova-hub-token-", dir=path.parent)
    try:
        try:
            os.fchmod(fd, 0o600)
        except (AttributeError, OSError):
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(token + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        try:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        except OSError:
            pass
    append_audit(settings.audit_path, "huggingface_token.configured", {"configured": True, "storage": "private local file"})
    return {"configured": True, "token_source": "private local token file", "token_returned": False,
            "note": "The token is stored locally with owner-only permissions. It is never included in API responses or audit logs."}


@router.delete("/token")
def clear_huggingface_token():
    """Remove only the locally stored token; environment-provided tokens are not modified."""
    path = settings.huggingface_token_file.expanduser()
    if path.is_symlink():
        raise HTTPException(403, "Refusing to remove a token path that is a symbolic link.")
    removed = False
    try:
        path.unlink()
        removed = True
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise HTTPException(500, "Could not remove the locally stored token.") from exc
    configured = bool(settings.huggingface_token or os.environ.get("NOVA_HUGGINGFACE_TOKEN", "").strip())
    append_audit(settings.audit_path, "huggingface_token.cleared", {"local_file_removed": removed, "environment_token_still_configured": configured})
    return {"configured": configured, "local_file_removed": removed,
            "environment_token_still_configured": configured, "token_returned": False}


class _HubRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Permit redirects only to HTTPS Hugging Face/CDN hosts used for model artifacts."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        host = (parsed.hostname or "").lower()
        allowed = host == "huggingface.co" or host.endswith(".huggingface.co") or host.endswith(".hf.co") or host.endswith(".amazonaws.com")
        if parsed.scheme != "https" or not allowed:
            raise urllib.error.HTTPError(newurl, code, "Blocked untrusted Hugging Face redirect", headers, fp)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and host != "huggingface.co" and not host.endswith(".huggingface.co"):
            # Signed CDN URLs carry their own authorization; never forward the Hub bearer token.
            redirected.remove_header("Authorization")
            redirected.remove_header("authorization")
        return redirected


def _request(url: str, *, timeout: int = 20):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "huggingface.co":
        raise HTTPException(400, "Hugging Face requests must target the official HTTPS host.")
    headers = {"User-Agent": "NOVA-local-model-manager/0.1", "Accept": "application/json"}
    token = _token()
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(_HubRedirectHandler())
    return opener.open(req, timeout=timeout)


def _hub_json(url: str) -> Any:
    try:
        with _request(url) as response:
            raw = response.read(5_000_001)
        if len(raw) > 5_000_000:
            raise HTTPException(502, "Hugging Face metadata response exceeded the safety limit.")
        return json.loads(raw.decode("utf-8"))
    except HTTPException:
        raise
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise HTTPException(401, "Hugging Face authentication is required for this repository.") from exc
        if exc.code == 403:
            raise HTTPException(403, "Hugging Face denied access; check model access and optional token.") from exc
        if exc.code == 404:
            raise HTTPException(404, "Hugging Face repository or revision was not found.") from exc
        if exc.code == 429:
            raise HTTPException(429, "Hugging Face rate limit reached; try again later.") from exc
        raise HTTPException(502, f"Hugging Face metadata request failed (HTTP {exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(502, "Could not reach or parse Hugging Face Hub metadata.") from exc


def _validate_repo(repo_id: str) -> str:
    repo_id = repo_id.strip()
    if not _REPO_ID.fullmatch(repo_id):
        raise HTTPException(422, "Repository must use the owner/repository format.")
    return repo_id


def _safe_filename(filename: str) -> tuple[str, str]:
    # Hub filenames may contain subfolders, but never traversal, absolute paths, or URL fragments.
    path = PurePosixPath(filename)
    if path.is_absolute() or not path.parts or any(p in {"", ".", ".."} for p in path.parts):
        raise HTTPException(422, "Unsafe model filename.")
    if "\\" in filename or "\x00" in filename:
        raise HTTPException(422, "Unsafe model filename.")
    ext = Path(path.name).suffix.lower()
    if ext not in _ALLOWED_ARTIFACTS:
        raise HTTPException(400, "Only .litertlm, .gguf, .tflite, .onnx, and .safetensors artifacts may be downloaded.")
    return path.as_posix(), ext


@router.get("/status")
def huggingface_status():
    features = get_feature_settings()
    return {"provider": "Hugging Face Hub", "enabled": features["model_hub_enabled"], "downloads_enabled": features["model_downloads_enabled"], "token_configured": bool(_token()),
            "token_source": ("environment/config setting" if (settings.huggingface_token or os.environ.get("NOVA_HUGGINGFACE_TOKEN", "").strip()) else ("private local token file" if _stored_token() else "not configured")),
            "cache_dir": str(settings.huggingface_cache_dir),
            "max_download_bytes": features["max_model_download_bytes"],
            "inference_policy": "Hugging Face supplies files/metadata only; chat inference remains LiteRT-LM-only."}


@router.get("/search")
def search_huggingface(q: str = Query(min_length=1, max_length=_MAX_QUERY), limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT), task: str | None = Query(default=None, max_length=60)):
    if not get_feature_settings()["model_hub_enabled"]:
        raise HTTPException(403, "Hugging Face model hub is disabled in Runtime Features settings.")
    query = q.strip()
    if not query:
        raise HTTPException(422, "Enter a search query.")
    params = {"search": query, "limit": str(limit), "sort": "downloads", "direction": "-1"}
    if task and task.strip():
        params["pipeline_tag"] = task.strip()
    url = "https://huggingface.co/api/models?" + urllib.parse.urlencode(params)
    results = _hub_json(url)
    if not isinstance(results, list):
        raise HTTPException(502, "Unexpected Hugging Face search response.")
    items = []
    for item in results[:limit]:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        items.append({
            "id": str(item["id"]),
            "author": item.get("author"),
            "downloads": item.get("downloads"),
            "likes": item.get("likes"),
            "pipeline_tag": item.get("pipeline_tag"),
            "library_name": item.get("library_name"),
            "private": item.get("private", False),
            "gated": item.get("gated", False),
            "tags": item.get("tags", [])[:20] if isinstance(item.get("tags"), list) else [],
            "last_modified": item.get("lastModified"),
        })
    return {"provider": "Hugging Face Hub", "query": query, "results": items, "download_requires_explicit_action": True}


@router.get("/files")
def list_huggingface_files(repo_id: str = Query(min_length=3, max_length=200), revision: str = Query(default="main", min_length=1, max_length=120)):
    if not get_feature_settings()["model_hub_enabled"]:
        raise HTTPException(403, "Hugging Face model hub is disabled in Runtime Features settings.")
    repo = _validate_repo(repo_id)
    if revision.startswith("/") or "\\" in revision or any(part in {"", ".", ".."} for part in revision.split("/")):
        raise HTTPException(422, "Revision must be a branch, tag, or commit identifier.")
    url = "https://huggingface.co/api/models/" + urllib.parse.quote(repo, safe="/") + "?" + urllib.parse.urlencode({"revision": revision})
    detail = _hub_json(url)
    siblings = detail.get("siblings", []) if isinstance(detail, dict) else []
    files = []
    for item in siblings:
        if not isinstance(item, dict) or not isinstance(item.get("rfilename"), str):
            continue
        name = item["rfilename"]
        ext = Path(name).suffix.lower()
        size = item.get("size")
        lfs = item.get("lfs")
        if size is None and isinstance(lfs, dict):
            size = lfs.get("size")
        files.append({"filename": name, "size_bytes": size, "downloadable_artifact": ext in _ALLOWED_ARTIFACTS})
    return {"repo_id": repo, "revision": revision, "files": files, "gated": detail.get("gated", False), "private": detail.get("private", False)}


@router.post("/download")
def download_huggingface_artifact(req: DownloadRequest):
    features = get_feature_settings()
    if not features["model_hub_enabled"] or not features["model_downloads_enabled"]:
        raise HTTPException(403, "Model downloads are disabled in Runtime Features settings.")
    repo = _validate_repo(req.repo_id)
    filename, extension = _safe_filename(req.filename)
    revision = req.revision.strip()
    if not revision or revision.startswith("/") or "\\" in revision or any(part in {"", ".", ".."} for part in revision.split("/")):
        raise HTTPException(422, "Revision must be a branch, tag, or commit identifier.")

    # Query metadata first so the UI cannot trick NOVA into blindly streaming arbitrary URLs.
    detail_url = "https://huggingface.co/api/models/" + urllib.parse.quote(repo, safe="/") + "?" + urllib.parse.urlencode({"revision": revision})
    detail = _hub_json(detail_url)
    siblings = detail.get("siblings", []) if isinstance(detail, dict) else []
    metadata = next((item for item in siblings if isinstance(item, dict) and item.get("rfilename") == filename), None)
    if metadata is None:
        raise HTTPException(404, "That exact file is not listed in the selected Hugging Face repository revision.")
    size = metadata.get("size")
    lfs = metadata.get("lfs")
    if size is None and isinstance(lfs, dict):
        size = lfs.get("size")
    limit = min(req.max_bytes or features["max_model_download_bytes"], features["max_model_download_bytes"])
    if isinstance(size, int) and size > limit:
        raise HTTPException(413, f"Artifact size ({size} bytes) exceeds the configured download limit ({limit} bytes).")

    settings.huggingface_cache_dir.mkdir(parents=True, exist_ok=True)
    destination_dir = (settings.huggingface_cache_dir / repo.replace("/", "--") / re.sub(r"[^A-Za-z0-9._-]", "_", revision)).resolve()
    cache_root = settings.huggingface_cache_dir.resolve()
    if cache_root not in destination_dir.parents:
        raise HTTPException(403, "Resolved model cache path escaped the configured cache directory.")
    destination = (destination_dir / filename).resolve()
    if cache_root not in destination.parents:
        raise HTTPException(403, "Resolved artifact path escaped the configured cache directory.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.is_file():
        cached_size = destination.stat().st_size
        if cached_size > limit:
            raise HTTPException(413, "Cached artifact exceeds the current configured download limit.")
        if isinstance(size, int) and cached_size != size:
            raise HTTPException(409, "Cached artifact size no longer matches Hugging Face metadata; inspect or remove the cached file.")
        digest = hashlib.sha256()
        with destination.open("rb") as stream:
            for block in iter(lambda: stream.read(_CHUNK), b""):
                digest.update(block)
        digest_hex = digest.hexdigest()
        append_audit(settings.audit_path, "huggingface_artifact_cache_hit", {"repo_id": repo, "revision": revision, "filename": filename, "sha256": digest_hex, "size_bytes": cached_size})
        return {"downloaded": True, "repo_id": repo, "revision": revision, "filename": filename,
                "file_path": str(destination), "size_bytes": cached_size,
                "sha256": digest_hex, "cached": True, "format": extension[1:],
                "inference_enabled": extension == ".litertlm"}

    encoded_filename = "/".join(urllib.parse.quote(part, safe="") for part in filename.split("/"))
    url = "https://huggingface.co/" + urllib.parse.quote(repo, safe="/") + "/resolve/" + urllib.parse.quote(revision, safe="") + "/" + encoded_filename
    fd, temp_name = tempfile.mkstemp(prefix=".nova-download-", dir=destination.parent)
    digest = hashlib.sha256()
    total = 0
    try:
        with os.fdopen(fd, "wb") as output, _request(url, timeout=60) as response:
            length = response.headers.get("Content-Length")
            if length and length.isdigit() and int(length) > limit:
                raise HTTPException(413, "Download response exceeds the configured size limit.")
            while True:
                block = response.read(_CHUNK)
                if not block:
                    break
                total += len(block)
                if total > limit:
                    raise HTTPException(413, "Download exceeded the configured size limit; partial artifact discarded.")
                output.write(block)
                digest.update(block)
            output.flush()
            os.fsync(output.fileno())
        if isinstance(size, int) and total != size:
            raise HTTPException(502, "Downloaded size did not match Hugging Face metadata; artifact discarded.")
        os.replace(temp_name, destination)
    except HTTPException:
        raise
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise HTTPException(401, "Hugging Face authentication is required for this file.") from exc
        if exc.code == 403:
            raise HTTPException(403, "Hugging Face denied the download; check gated access and token.") from exc
        if exc.code == 404:
            raise HTTPException(404, "The selected model file or revision was not found.") from exc
        raise HTTPException(502, f"Hugging Face download failed (HTTP {exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HTTPException(502, "Download failed; no artifact was registered.") from exc
    finally:
        try:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        except OSError:
            pass

    digest_hex = digest.hexdigest()
    append_audit(settings.audit_path, "huggingface_artifact_downloaded", {"repo_id": repo, "revision": revision, "filename": filename, "sha256": digest_hex, "size_bytes": total, "format": extension[1:]})
    return {"downloaded": True, "repo_id": repo, "revision": revision, "filename": filename,
            "file_path": str(destination), "size_bytes": total, "sha256": digest_hex,
            "cached": False, "format": extension[1:], "inference_enabled": extension == ".litertlm",
            "next_step": "Register this local artifact in Model Manager and select it only if it is a compatible LiteRT-LM model."}

@router.get("/cache")
def list_local_model_cache():
    """List cached artifacts without hashing, loading, or executing model files."""
    root = settings.huggingface_cache_dir.expanduser().resolve()
    if not root.exists():
        return {"cache_dir": str(root), "files": [], "file_count": 0, "total_bytes": 0, "truncated": False}
    files = []
    total_bytes = 0
    truncated = False
    try:
        for path in root.rglob("*"):
            # Never follow symlinks or expose transient partial downloads.
            if path.is_symlink() or not path.is_file() or path.name.startswith(".nova-download-"):
                continue
            try:
                resolved = path.resolve(strict=True)
                if root not in resolved.parents:
                    continue
                size = resolved.stat().st_size
            except OSError:
                continue
            if len(files) >= 1000:
                truncated = True
                break
            relative = resolved.relative_to(root).as_posix()
            files.append({"relative_path": relative, "file_path": str(resolved), "size_bytes": size,
                          "format": resolved.suffix.lower().lstrip(".")})
            total_bytes += size
    except OSError as exc:
        raise HTTPException(500, "Unable to inspect the local model cache.") from exc
    files.sort(key=lambda item: item["relative_path"].casefold())
    return {"cache_dir": str(root), "files": files, "file_count": len(files),
            "total_bytes": total_bytes, "truncated": truncated,
            "note": "Inventory only: files are not loaded or executed; registration status is not inferred."}
