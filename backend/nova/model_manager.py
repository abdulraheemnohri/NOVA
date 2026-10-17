"""Local model catalog and metadata registry. Inference remains LiteRT-LM-only."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from nova.config import settings

router = APIRouter(prefix="/api/models", tags=["local model management"])

# This is a curated catalog, not a claim to enumerate every model published online.
# Non-text models are inventory/planning entries until a local runtime adapter is implemented.
CATALOG: list[dict[str, Any]] = [
    {"id":"litert-functiongemma-270m","name":"FunctionGemma 270M","kind":"tool_calling","format":"litertlm","runtime":"LiteRT-LM","ram_gb_min":2,"device_tier":"low_end","modalities":["text"],"status":"catalog_only","notes":"Small function/action model; verify exact LiteRT-LM artifact and tool schema."},
    {"id":"litert-qwen3-4b-thinking","name":"Qwen3 4B Thinking","kind":"reasoning","format":"litertlm","runtime":"LiteRT-LM","ram_gb_min":6,"device_tier":"mid_range","modalities":["text"],"status":"catalog_only","notes":"Quantization and context length determine practical memory use."},
    {"id":"litert-small-instruct","name":"Small instruction model (user supplied)","kind":"chat","format":"litertlm","runtime":"LiteRT-LM","ram_gb_min":2,"device_tier":"low_end","modalities":["text"],"status":"configured","notes":"Use only after validating the model file and runtime compatibility."},
    {"id":"voice-whisper-small","name":"Whisper small / compatible ASR export","kind":"speech_to_text","format":"onnx_or_litert","runtime":"not_integrated","ram_gb_min":2,"device_tier":"low_end","modalities":["audio"],"status":"catalog_only","notes":"Speech recognition inventory entry; no voice runtime is wired yet."},
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
    con.commit()
    return con

def active_model_id() -> str:
    con = _connect()
    try:
        row = con.execute("SELECT value FROM nova_local_settings WHERE key='active_model_id'").fetchone()
        return str(row["value"]) if row else settings.litert_model
    finally:
        con.close()

def _local_registry() -> list[dict[str, Any]]:
    con = _connect()
    try:
        return [dict(row) for row in con.execute("SELECT * FROM model_registry ORDER BY created_at DESC")]
    finally:
        con.close()

@router.get("/catalog")
def model_catalog():
    return {"catalog": CATALOG, "device_profiles": DEVICE_PROFILES,
            "runtime_policy": "LiteRT-LM-only for chat inference; other runtime types are inventory-only."}

@router.get("")
def list_models():
    active = active_model_id()
    local = _local_registry()
    entries = [dict(item, active=(item["id"] == active)) for item in CATALOG]
    entries.extend(dict(item, active=(item["model_id"] == active), status="registered_local") for item in local)
    return {"active_model_id": active, "runtime": "LiteRT-LM", "models": entries}

@router.post("/select")
def select_model(req: SelectModelRequest):
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
    if fmt != "litertlm":
        raise HTTPException(400, "This model type has no LiteRT-LM inference adapter; it cannot be selected for chat.")
    con = _connect()
    try:
        con.execute("INSERT INTO nova_local_settings(key,value) VALUES('active_model_id',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (req.model_id,))
        con.commit()
    finally:
        con.close()
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
    if req.sha256 and req.sha256.lower() != actual:
        raise HTTPException(422, "SHA-256 mismatch; model was not registered.")
    con = _connect()
    try:
        con.execute("INSERT INTO model_registry(model_id,name,kind,file_path,format,sha256) VALUES(?,?,?,?,?,?) ON CONFLICT(model_id) DO UPDATE SET name=excluded.name,kind=excluded.kind,file_path=excluded.file_path,format=excluded.format,sha256=excluded.sha256",
                    (req.model_id, req.name, req.kind, str(resolved), req.format.lower(), actual))
        con.commit()
    finally:
        con.close()
    return {"registered": True, "model_id": req.model_id, "sha256": actual,
            "size_bytes": resolved.stat().st_size, "format": req.format.lower(),
            "inference_enabled": req.format.lower() == "litertlm"}
