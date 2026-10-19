"""Local model catalog and metadata registry. Inference remains LiteRT-LM-only."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from nova.config import settings
from nova.audit import append_audit

router = APIRouter(prefix="/api/models", tags=["local model management"])

# This is a curated catalog, not a claim to enumerate every model published online.
# Non-text models are inventory/planning entries until a local runtime adapter is implemented.
CATALOG: list[dict[str, Any]] = [
    {"id":"litert-functiongemma-270m","name":"FunctionGemma 270M","kind":"tool_calling","format":"litertlm","runtime":"LiteRT-LM","ram_gb_min":2,"device_tier":"low_end","modalities":["text"],"status":"catalog_only","notes":"Small function/action model; verify exact LiteRT-LM artifact and tool schema."},
    {"id":"litert-qwen3-4b-thinking","name":"Qwen3 4B Thinking","kind":"reasoning","format":"litertlm","runtime":"LiteRT-LM","ram_gb_min":6,"device_tier":"mid_range","modalities":["text"],"status":"catalog_only","notes":"Quantization and context length determine practical memory use."},
    {"id":"litert-small-instruct","name":"Small instruction model (user supplied)","kind":"chat","format":"litertlm","runtime":"LiteRT-LM","ram_gb_min":2,"device_tier":"low_end","modalities":["text"],"status":"configured","notes":"Use only after validating the model file and runtime compatibility."},
    {"id":"whisper-cpp-base","name":"Whisper.cpp GGML base model","kind":"speech_to_text","format":"ggml","runtime":"whisper.cpp","ram_gb_min":2,"device_tier":"low_end","modalities":["audio"],"status":"runtime_supported","notes":"Used by the explicit local WAV transcription endpoint when NOVA_WHISPER_MODEL_PATH points to a compatible GGML .bin file; not selectable for chat."},
    {"id":"voice-whisper-small","name":"Whisper small / compatible ASR export","kind":"speech_to_text","format":"onnx_or_litert","runtime":"task_adapter_pending","ram_gb_min":2,"device_tier":"low_end","modalities":["audio"],"status":"catalog_only","notes":"Other Whisper exports require a matching task-specific runtime adapter."},
    {"id":"voice-whisper-large-v3","name":"Whisper large-v3 / compatible ASR export","kind":"speech_to_text","format":"onnx_or_litert","runtime":"not_integrated","ram_gb_min":8,"device_tier":"high_end","modalities":["audio"],"status":"catalog_only","notes":"High memory and compute demand; no voice runtime is wired yet."},
    {"id":"voice-piper-tts","name":"Piper-compatible TTS voice","kind":"text_to_speech","format":"onnx","runtime":"not_integrated","ram_gb_min":1,"device_tier":"low_end","modalities":["audio"],"status":"catalog_only","notes":"Voice packs vary by language; TTS is not integrated yet."},
    {"id":"vision-mobile","name":"Mobile vision encoder / detector","kind":"vision","format":"tflite_or_litert","runtime":"not_integrated","ram_gb_min":2,"device_tier":"low_end","modalities":["image"],"status":"catalog_only","notes":"Image understanding is not integrated yet."},
    {"id":"vision-large","name":"Large vision-language model","kind":"vision_language","format":"litertlm_or_onnx","runtime":"not_integrated","ram_gb_min":12,"device_tier":"high_end","modalities":["image","text"],"status":"catalog_only","notes":"Requires a compatible local runtime and substantial memory."},
    {"id":"embedding-small","name":"Small local text embedding model","kind":"embedding","format":"onnx_or_litert","runtime":"not_integrated","ram_gb_min":1,"device_tier":"low_end","modalities":["text"],"status":"catalog_only","notes":"Embeddings/vector retrieval are not currently wired to NOVA."},
    {"id":"reranker-small","name":"Small local reranker","kind":"reranking","format":"onnx_or_litert","runtime":"not_integrated","ram_gb_min":2,"device_tier":"low_end","modalities":["text"],"status":"catalog_only","notes":"Retrieval reranking is not currently integrated."},
    {"id":"translation-small","name":"Compact translation model","kind":"translation","format":"onnx_or_litert","runtime":"not_integrated","ram_gb_min":2,"device_tier":"low_end","modalities":["text"],"status":"catalog_only","notes":"Translation pipeline is not currently integrated."},
    {"id":"ocr-mobile","name":"Mobile OCR model","kind":"ocr","format":"tflite_or_onnx","runtime":"not_integrated","ram_gb_min":1,"device_tier":"low_end","modalities":["image","text"],"status":"catalog_only","notes":"OCR/document image extraction is not currently integrated."},
    {"id":"classify-small","name":"Compact text classifier","kind":"classification","format":"onnx_or_litert","runtime":"not_integrated","ram_gb_min":1,"device_tier":"low_end","modalities":["text"],"status":"catalog_only","notes":"Classification is cataloged but no separate adapter is enabled."},
]

DEVICE_PROFILES = [
    {"id":"low_end","label":"Low-end / constrained","ram_gb_max":4,"recommended_active_models":1,"policy":"Small quantized model, short context, CPU-first; avoid loading multiple models."},
    {"id":"mid_range","label":"Mid-range","ram_gb_max":8,"recommended_active_models":1,"policy":"One modest quantized model; monitor memory before increasing context."},
    {"id":"high_end","label":"High-end / workstation","ram_gb_max":None,"recommended_active_models":1,"policy":"Larger local models may fit; measure actual RAM/VRAM and runtime support."},
]

class SelectModelRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=120)

class RegisterModelRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9._-]+$")
    name: str = Field(min_length=1, max_length=160)
    kind: str = Field(min_length=1, max_length=50)
    file_path: str = Field(min_length=1, max_length=1000)
    format: str = Field(min_length=1, max_length=50)
    sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")

class ModelActivationRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=120)
    enabled: bool

def _connect():
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(settings.database_path)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS model_registry (
        model_id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
        file_path TEXT NOT NULL, format TEXT NOT NULL, sha256 TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    con.execute("""CREATE TABLE IF NOT EXISTS nova_local_settings (
        key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS model_status (
        model_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    con.commit()
    return con

def active_model_id() -> str:
    con = _connect()
    try:
        row = con.execute("SELECT value FROM nova_local_settings WHERE key='active_model_id'").fetchone()
        return str(row["value"]) if row else settings.litert_model
    finally:
        con.close()

def _model_enabled(model_id: str) -> bool:
    con = _connect()
    try:
        row = con.execute("SELECT enabled FROM model_status WHERE model_id=?", (model_id,)).fetchone()
        return bool(row["enabled"]) if row else True
    finally:
        con.close()

def _known_model(model_id: str) -> bool:
    if any(item["id"] == model_id for item in CATALOG):
        return True
    return any(item["model_id"] == model_id for item in _local_registry())

def _local_registry() -> list[dict[str, Any]]:
    con = _connect()
    try:
        return [dict(row) for row in con.execute("SELECT * FROM model_registry ORDER BY created_at DESC")]
    finally:
        con.close()

def _memory_snapshot() -> dict[str, Any]:
    """Read host RAM without requiring psutil or launching subprocesses."""
    total = available = None
    if Path("/proc/meminfo").is_file():
        try:
            values = {}
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                key, _, rest = line.partition(":")
                parts = rest.strip().split()
                if parts and parts[0].isdigit():
                    values[key] = int(parts[0]) * 1024
            total = values.get("MemTotal")
            available = values.get("MemAvailable") or values.get("MemFree")
        except (OSError, ValueError):
            pass
    if total is None and platform.system() == "Windows":
        try:
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                total, available = int(status.ullTotalPhys), int(status.ullAvailPhys)
        except (AttributeError, OSError, TypeError):
            pass
    gib = total / (1024 ** 3) if total is not None else None
    tier = "unknown" if gib is None else "low_end" if gib <= 4 else "mid_range" if gib <= 8 else "high_end"
    budget = int(max(0, available or 0) * 0.60) if available is not None else None
    return {"platform": platform.platform(), "architecture": platform.machine(),
            "ram_total_bytes": total, "ram_available_bytes": available,
            "ram_total_gib": round(gib, 2) if gib is not None else None,
            "ram_available_gib": round(available / (1024 ** 3), 2) if available is not None else None,
            "recommended_profile": tier, "conservative_model_memory_budget_bytes": budget,
            "gpu_vram_bytes": None,
            "notes": ["RAM readings are advisory, not a guarantee that a model fits.",
                      "GPU/VRAM detection is not implemented on every platform.",
                      "Context/KV cache, runtime overhead and concurrent processes reduce usable memory."]}


def _model_kind_for_path(path: Path) -> str:
    name, parent = path.name.lower(), str(path.parent).lower()
    if any(word in name or word in parent for word in ("whisper", "asr", "speech")):
        return "speech_to_text"
    if any(word in name or word in parent for word in ("piper", "tts", "voice")):
        return "text_to_speech"
    if any(word in name or word in parent for word in ("embed", "sentence-transform", "e5-", "bge-")):
        return "embedding"
    if any(word in name or word in parent for word in ("rerank", "cross-encoder")):
        return "reranking"
    if any(word in name or word in parent for word in ("ocr", "vision", "clip", "llava")):
        return "vision"
    return "chat" if path.suffix.lower() in {".litertlm", ".gguf"} else "unknown"


@router.get("/device-profile")
def device_profile():
    snapshot = _memory_snapshot()
    profiles = {p["id"]: p for p in DEVICE_PROFILES}
    return {"device": snapshot, "profile": profiles.get(snapshot["recommended_profile"]),
            "profiles": DEVICE_PROFILES,
            "runtime_policy": "Recommendations only; verify artifact/runtime support and context memory before loading."}


@router.post("/discover")
def discover_local_models():
    """Automatically inventory artifacts under NOVA's known model/cache roots only."""
    roots = [settings.huggingface_cache_dir.expanduser(), Path("./data/models").expanduser()]
    normalized_roots: list[Path] = []
    for root in roots:
        try:
            resolved = root.resolve()
            if resolved not in normalized_roots:
                normalized_roots.append(resolved)
        except OSError:
            continue
    existing = {str(Path(item["file_path"]).resolve()) for item in _local_registry()
                if item.get("file_path")}
    allowed = {".litertlm", ".gguf", ".tflite", ".onnx", ".safetensors", ".bin"}
    candidates: list[Path] = []
    seen: set[str] = set()
    truncated = False
    visited = 0
    for root in normalized_roots:
        if not root.is_dir():
            continue
        try:
            for directory, dirnames, filenames in os.walk(root, followlinks=False):
                dirnames[:] = [d for d in dirnames if not (Path(directory) / d).is_symlink()
                               and d not in {".git", "__pycache__"}]
                for filename in filenames:
                    visited += 1
                    if visited > 10000:
                        truncated = True
                        break
                    path = Path(directory) / filename
                    if path.suffix.lower() not in allowed or path.is_symlink():
                        continue
                    try:
                        resolved = path.resolve(strict=True)
                        if not resolved.is_file() or str(resolved) in seen:
                            continue
                        seen.add(str(resolved))
                        if str(resolved) not in existing:
                            candidates.append(resolved)
                            if len(candidates) >= 200:
                                truncated = True
                                break
                    except OSError:
                        continue
                if truncated:
                    break
        except OSError:
            continue
        if truncated:
            break
    registered: list[dict[str, Any]] = []
    for path in candidates:
        try:
            size = path.stat().st_size
            if size <= 0:
                continue
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            sha, fmt = digest.hexdigest(), path.suffix.lower().lstrip(".")
            kind = _model_kind_for_path(path)
            model_id = "local-" + hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]
            con = _connect()
            try:
                con.execute("INSERT OR IGNORE INTO model_registry(model_id,name,kind,file_path,format,sha256) VALUES(?,?,?,?,?,?)",
                            (model_id, path.stem[:160], kind, str(path), fmt, sha))
                con.commit()
            finally:
                con.close()
            registered.append({"model_id": model_id, "name": path.stem, "kind": kind,
                               "format": fmt, "file_path": str(path), "size_bytes": size,
                               "sha256": sha, "chat_selectable": fmt == "litertlm"})
        except (OSError, sqlite3.Error):
            continue
    if registered:
        append_audit(settings.audit_path, "local_models_auto_discovered",
                     {"count": len(registered), "formats": sorted({m["format"] for m in registered})})
    return {"registered_count": len(registered), "registered": registered,
            "roots_scanned": [str(p) for p in normalized_roots], "truncated": truncated,
            "note": "Inventory only: no model is downloaded, executed, or activated. Only .litertlm artifacts are eligible for LiteRT-LM chat."}


@router.get("/catalog")
def model_catalog():
    return {"catalog": CATALOG, "device_profiles": DEVICE_PROFILES,
            "runtime_policy": "LiteRT-LM-only for chat inference; other runtime types are inventory-only."}

@router.get("")
def list_models():
    active = active_model_id()
    local = _local_registry()
    entries = [dict(item, active=(item["id"] == active), enabled=_model_enabled(item["id"]), deactivation_protected=(item["id"] == settings.litert_model)) for item in CATALOG]
    entries.extend(dict(item, active=(item["model_id"] == active), enabled=_model_enabled(item["model_id"]), deactivation_protected=(item["model_id"] == settings.litert_model), status="registered_local") for item in local)
    return {"active_model_id": active, "runtime": "LiteRT-LM", "models": entries}

@router.put("/activation")
def set_model_activation(req: ModelActivationRequest):
    if not _known_model(req.model_id):
        raise HTTPException(404, "Model is not in the catalog or local registry.")
    if not req.enabled and req.model_id == settings.litert_model:
        raise HTTPException(409, "The configured LiteRT-LM fallback cannot be disabled; change NOVA_LITERT_MODEL in the local environment first.")
    was_selected = False
    con = _connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        selected = con.execute("SELECT value FROM nova_local_settings WHERE key='active_model_id'").fetchone()
        was_selected = (str(selected["value"]) if selected else settings.litert_model) == req.model_id
        if not req.enabled and was_selected:
            # Fall back to the operator-configured LiteRT-LM model before marking this model inactive.
            con.execute("DELETE FROM nova_local_settings WHERE key='active_model_id' AND value=?", (req.model_id,))
        con.execute(
            "INSERT INTO model_status(model_id,enabled,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) "
            "ON CONFLICT(model_id) DO UPDATE SET enabled=excluded.enabled,updated_at=CURRENT_TIMESTAMP",
            (req.model_id, int(req.enabled)),
        )
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    fallback = active_model_id()
    append_audit(settings.audit_path, "model_activation_changed", {"model_id": req.model_id, "enabled": req.enabled, "previously_selected": was_selected, "active_model_id": fallback})
    return {"model_id": req.model_id, "enabled": req.enabled, "status": "active" if req.enabled else "inactive", "active_model_id": fallback}

@router.post("/select")
def select_model(req: SelectModelRequest):
    if not _model_enabled(req.model_id):
        raise HTTPException(409, "This model is inactive. Activate it before selecting it for chat.")
    candidate = next((item for item in _local_registry() if item["model_id"] == req.model_id), None)
    if candidate is None:
        catalog_entry = next((item for item in CATALOG if item["id"] == req.model_id), None)
        if catalog_entry and catalog_entry.get("format") != "litertlm":
            raise HTTPException(400, "This model type has no LiteRT-LM inference adapter; it cannot be selected for chat.")
        if req.model_id == settings.litert_model:
            candidate = {"model_id": settings.litert_model, "format": "litertlm"}
        elif catalog_entry:
            raise HTTPException(409, "Catalog entry is not registered as a local artifact. Register and verify the model file before selecting it.")
        else:
            raise HTTPException(404, "Model is not in the catalog or local registry.")
    fmt = candidate.get("format", "")
    if candidate.get("file_path"):
        artifact = Path(str(candidate["file_path"]))
        if not artifact.is_file():
            raise HTTPException(409, "Registered model artifact is missing; register it again after restoring the file.")
        if fmt == "litertlm" and artifact.suffix.lower() != ".litertlm":
            raise HTTPException(422, "LiteRT-LM selection requires a .litertlm artifact file.")
        digest = hashlib.sha256()
        try:
            with artifact.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
        except OSError as exc:
            raise HTTPException(409, "Registered model artifact cannot be read; selection was refused.") from exc
        if digest.hexdigest() != candidate.get("sha256"):
            raise HTTPException(409, "Registered model checksum changed; selection was refused. Re-register only after reviewing the artifact.")
    if fmt != "litertlm":
        raise HTTPException(400, "This model type has no LiteRT-LM inference adapter; it cannot be selected for chat.")
    con = _connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        status = con.execute("SELECT enabled FROM model_status WHERE model_id=?", (req.model_id,)).fetchone()
        if status is not None and not bool(status["enabled"]):
            con.rollback()
            raise HTTPException(409, "This model is inactive. Activate it before selecting it for chat.")
        con.execute("INSERT INTO nova_local_settings(key,value) VALUES('active_model_id',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (req.model_id,))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    append_audit(settings.audit_path, "model_selected", {"model_id": req.model_id, "runtime": "LiteRT-LM"})
    return {"active_model_id": req.model_id, "runtime": "LiteRT-LM", "persisted_locally": True}

@router.post("/register")
def register_local_model(req: RegisterModelRequest):
    # Registration only inventories a file. It does not download, execute, or trust the artifact.
    path = Path(req.file_path).expanduser()
    if not path.is_absolute():
        raise HTTPException(400, "Provide an absolute path to a model artifact on this device.")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise HTTPException(400, "Model artifact does not exist or cannot be accessed.") from exc
    if not resolved.is_file():
        raise HTTPException(400, "Register a single model artifact file; directory bundles are not supported yet.")
    digest = hashlib.sha256()
    try:
        with resolved.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise HTTPException(400, "Unable to read model artifact for checksum.") from exc
    actual = digest.hexdigest()
    if req.format.lower() == "litertlm" and resolved.suffix.lower() != ".litertlm":
        raise HTTPException(422, "LiteRT-LM artifacts must use the .litertlm file extension.")
    if req.sha256 and req.sha256.lower() != actual:
        raise HTTPException(422, "SHA-256 mismatch; model was not registered.")
    con = _connect()
    try:
        con.execute("INSERT INTO model_registry(model_id,name,kind,file_path,format,sha256) VALUES(?,?,?,?,?,?) ON CONFLICT(model_id) DO UPDATE SET name=excluded.name,kind=excluded.kind,file_path=excluded.file_path,format=excluded.format,sha256=excluded.sha256",
                    (req.model_id, req.name, req.kind, str(resolved), req.format.lower(), actual))
        con.commit()
    finally:
        con.close()
    append_audit(settings.audit_path, "model_registered", {"model_id": req.model_id, "format": req.format.lower(), "sha256": actual, "size_bytes": resolved.stat().st_size})
    return {"registered": True, "model_id": req.model_id, "sha256": actual,
            "size_bytes": resolved.stat().st_size, "format": req.format.lower(),
            "inference_enabled": req.format.lower() == "litertlm"}
