"""Discovery and adapters for optional local model runtimes.

LiteRT-LM remains NOVA's only chat-inference runtime. Other runtimes are
explicitly scoped to specialized tasks and are never silently selected as fallbacks.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from nova.audit import append_audit
from nova.config import settings
from nova.litert import health as litert_health

router = APIRouter(prefix="/api/runtimes", tags=["model runtimes"])

_MAX_WAV_BYTES = 25_000_000


class SynthesisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


def _resolve_executable(configured: str, candidates: tuple[str, ...]) -> str | None:
    if configured.strip():
        path = Path(configured).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
        # An invalid explicit path must not silently select a different binary.
        return None
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return str(Path(found).resolve())
    return None


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False



def _distribution_version(*names: str) -> str | None:
    """Return installed distribution version without importing or executing runtime code."""
    for name in names:
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return None


def runtime_inventory() -> dict[str, Any]:
    """Return installed/configured runtime visibility without launching binaries."""
    whisper_cli = _resolve_executable(settings.whisper_cli_path, ("whisper-cli",))
    piper_cli = _resolve_executable(settings.piper_cli_path, ("piper",))
    tesseract_cli = _resolve_executable(settings.tesseract_cli_path, ("tesseract",))
    ffmpeg_cli = _resolve_executable(settings.ffmpeg_cli_path, ("ffmpeg",))
    llama_server = _resolve_executable(settings.llama_cpp_server_path, ("llama-server",))
    whisper_model = settings.whisper_model_path.expanduser()
    piper_model = settings.piper_model_path.expanduser()
    piper_metadata = Path(str(piper_model) + ".json")
    litert = litert_health()
    onnx_available = settings.onnxruntime_enabled and _module_available("onnxruntime")
    tflite_available = _module_available("tflite_runtime") or _module_available("ai_edge_litert")
    transformers_available = _module_available("transformers")
    runtimes = [
        {
            "id": "ffmpeg-audio", "name": "FFmpeg audio converter",
            "purpose": "Local audio normalization for offline transcription", "role": "audio_preprocessor",
            "detected": ffmpeg_cli is not None, "executable": ffmpeg_cli,
            "configured": bool(settings.ffmpeg_cli_path or ffmpeg_cli),
            "status": "ready" if ffmpeg_cli else "not_available",
            "policy": "Used only when the operator explicitly uploads a non-WAV file for local transcription.",
        },
        {
            "id": "tesseract-ocr", "name": "Tesseract OCR",
            "purpose": "Local image-to-text extraction", "role": "image_to_text",
            "detected": tesseract_cli is not None, "executable": tesseract_cli,
            "configured": bool(settings.tesseract_cli_path or tesseract_cli),
            "status": "needs_setup" if not tesseract_cli else ("ready" if _module_available("PIL") else "needs_setup"),
            "policy": "Explicit local OCR endpoint only; image pixels and time are bounded.",
        },
        {
            "id": "litert-lm", "name": "LiteRT-LM",
            "purpose": "Primary chat/reasoning inference", "role": "primary_chat",
            "detected": litert.get("reachable") is True, "configured": True,
            "endpoint": litert.get("base_url", settings.litert_base_url),
            "model_configured": settings.litert_model,
            "status": "ready" if litert.get("reachable") is True else "unavailable",
            "policy": "Only chat inference runtime; no automatic fallback.",
        },
        {
            "id": "whisper-cpp", "name": "whisper.cpp",
            "purpose": "Offline audio transcription / speech-to-text", "role": "speech_to_text",
            "detected": whisper_cli is not None, "executable": whisper_cli,
            "model_path": str(whisper_model), "model_present": whisper_model.is_file(),
            "configured": bool(settings.whisper_cli_path or whisper_cli),
            "status": "ready" if whisper_cli and whisper_model.is_file() else "needs_setup",
            "policy": "Used only by the explicit transcription endpoint.",
        },
        {
            "id": "piper-tts", "name": "Piper",
            "purpose": "Local text-to-speech", "role": "text_to_speech",
            "detected": piper_cli is not None, "executable": piper_cli,
            "model_path": str(piper_model), "model_present": piper_model.is_file(),
            "model_metadata_present": piper_metadata.is_file(),
            "configured": bool(settings.piper_cli_path or piper_cli),
            "status": "ready" if piper_cli and piper_model.is_file() and piper_metadata.is_file() else "needs_setup",
            "policy": "Used only by the explicit local speech synthesis endpoint."
        },
        {
            "id": "onnx-runtime", "name": "ONNX Runtime",
            "purpose": "Specialized ONNX models: embeddings, OCR, classifiers and compatible audio models",
            "role": "specialized_model_runtime", "detected": onnx_available,
            "version": _distribution_version("onnxruntime") if onnx_available else None,
            "configured": settings.onnxruntime_enabled,
            "status": "ready" if onnx_available else "not_available",
            "policy": "Inventory only until a task-specific model adapter is enabled.",
        },
        {
            "id": "tflite-runtime", "name": "TensorFlow Lite / LiteRT Python packages",
            "purpose": "Compatible edge vision/audio/classification models",
            "role": "specialized_model_runtime", "detected": tflite_available,
            "version": _distribution_version("tflite-runtime", "ai-edge-litert") if tflite_available else None,
            "configured": True, "status": "ready" if tflite_available else "not_available",
            "policy": "Inventory only; no silent chat-runtime substitution.",
        },
        {
            "id": "llama-cpp", "name": "llama.cpp server",
            "purpose": "Optional GGUF runtime for future explicit model-specific integrations",
            "role": "optional_runtime_not_used_for_chat", "detected": llama_server is not None,
            "executable": llama_server, "configured": bool(settings.llama_cpp_server_path or llama_server),
            "status": "detected_not_enabled" if llama_server else "not_available",
            "policy": "Not used for NOVA chat; no automatic fallback.",
        },
        {
            "id": "transformers", "name": "Hugging Face Transformers",
            "purpose": "Future specialized local pipelines where supported",
            "role": "specialized_model_runtime", "detected": transformers_available,
            "version": _distribution_version("transformers") if transformers_available else None,
            "configured": False,
            "status": "detected_not_enabled" if transformers_available else "not_available",
            "policy": "Not loaded automatically; no remote inference.",
        },
    ]
    return {
        "primary_chat_runtime": "litert-lm",
        "automatic_fallback": False,
        "runtimes": runtimes,
        "notes": [
            "Detection confirms executable/package presence only; it does not prove model compatibility or accelerator support.",
            "Optional runtimes are task-scoped. NOVA never starts a server or downloads model files automatically.",
            "Tesseract OCR requires a local tesseract executable and optional Pillow image validation; it is not used for chat.",
            "whisper.cpp accepts WAV directly; common formats are normalized with local FFmpeg when its executable is installed. No remote conversion is used.",
        ],
    }


@router.get("")
def list_runtimes():
    return runtime_inventory()



@router.post("/ocr/extract")
async def extract_image_text(file: UploadFile = File(...)):
    """Run explicitly requested OCR with a preinstalled local Tesseract binary."""
    filename = Path(file.filename or "image").name
    suffix = Path(filename).suffix.lower()
    allowed = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
    if suffix not in allowed:
        raise HTTPException(415, "OCR accepts PNG, JPEG, TIFF, BMP or WebP images only.")
    data = await file.read(settings.ocr_max_upload_bytes + 1)
    if not data or len(data) > settings.ocr_max_upload_bytes:
        raise HTTPException(413, "Image is empty or exceeds the configured OCR upload limit.")
    executable = _resolve_executable(settings.tesseract_cli_path, ("tesseract",))
    if not executable:
        raise HTTPException(503, "Tesseract was not found. Install it locally or set NOVA_TESSERACT_CLI_PATH.")
    try:
        from PIL import Image
        from PIL import UnidentifiedImageError
    except ImportError as exc:
        raise HTTPException(503, "Image OCR requires the optional Pillow package for safe image validation.") from exc
    import io
    try:
        with Image.open(io.BytesIO(data)) as probe:
            if probe.format not in {"PNG", "JPEG", "TIFF", "BMP", "WEBP"}:
                raise HTTPException(415, "Unsupported image format.")
            width, height = probe.size
            if width < 1 or height < 1 or width * height > 40_000_000 or max(width, height) > 10000:
                raise HTTPException(413, "Image dimensions exceed the 40-megapixel safety limit.")
            probe.verify()
        with Image.open(io.BytesIO(data)) as source:
            normalized = source.convert("RGB")
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(422, "Upload is not a valid supported image.") from exc
    workspace = settings.workspace.resolve()
    ocr_dir = workspace / ".nova-ocr"
    if ocr_dir.is_symlink():
        raise HTTPException(403, "OCR work directory must not be a symbolic link.")
    ocr_dir.mkdir(parents=True, exist_ok=True)
    if workspace not in ocr_dir.resolve().parents:
        raise HTTPException(403, "OCR work directory must remain inside the NOVA workspace.")
    from tempfile import TemporaryDirectory
    try:
        with TemporaryDirectory(prefix="ocr-", dir=ocr_dir) as temp_dir:
            image_path = Path(temp_dir) / "input.png"
            normalized.save(image_path, format="PNG", optimize=False)
            try:
                result = subprocess.run(
                    [executable, str(image_path), "stdout", "--psm", "6"],
                    capture_output=True, text=True, timeout=settings.ocr_timeout_seconds,
                    check=False, shell=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise HTTPException(504, "Local OCR exceeded its configured timeout.") from exc
            if result.returncode != 0:
                raise HTTPException(502, "Local Tesseract OCR failed; inspect the local runtime installation.")
            text = (result.stdout or "").strip()
            if len(text) > 1_000_000:
                raise HTTPException(413, "OCR output exceeds the 1 MB text limit.")
    finally:
        normalized.close()
    append_audit(settings.audit_path, "runtime.ocr.completed", {
        "filename": filename, "image_sha256": hashlib.sha256(data).hexdigest(),
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "text_chars": len(text), "runtime": "tesseract",
    })
    return {"runtime": "tesseract", "source_name": filename, "text": text, "characters": len(text),
            "note": "Local OCR only. Review extracted text before treating it as trusted."}


@router.post("/piper/synthesize")
def synthesize_with_piper(req: SynthesisRequest):
    """Synthesize speech with a preinstalled local Piper executable and voice model."""
    if not req.text.strip():
        raise HTTPException(422, "Text to synthesize must not be blank.")
    executable = _resolve_executable(settings.piper_cli_path, ("piper",))
    if not executable:
        raise HTTPException(503, "Piper was not found. Set NOVA_PIPER_CLI_PATH to its executable.")
    model = settings.piper_model_path.expanduser()
    if not model.is_file() or model.suffix.lower() != ".onnx":
        raise HTTPException(503, "Piper voice model is missing. Set NOVA_PIPER_MODEL_PATH to a local .onnx voice.")
    sidecar = Path(str(model) + ".json")
    if not sidecar.is_file():
        raise HTTPException(503, "Piper voice metadata sidecar (.onnx.json) is missing.")
    workspace = settings.workspace.resolve()
    audio_dir = workspace / ".nova-audio"
    if audio_dir.is_symlink():
        raise HTTPException(403, "Audio work directory must not be a symbolic link.")
    audio_dir.mkdir(parents=True, exist_ok=True)
    if workspace not in audio_dir.resolve().parents:
        raise HTTPException(403, "Audio work directory must remain inside the NOVA workspace.")
    output_path = audio_dir / f"{uuid.uuid4().hex}-speech.wav"
    try:
        timeout = max(10, min(settings.whisper_timeout_seconds, 600))
        command = [executable, "--model", str(model.resolve()), "--output_file", str(output_path)]
        try:
            completed = subprocess.run(
                command, input=req.text, shell=False, capture_output=True,
                text=True, timeout=timeout, check=False, cwd=str(workspace),
            )
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(504, "Piper speech synthesis timed out.") from exc
        if completed.returncode != 0:
            append_audit(settings.audit_path, "runtime.piper.failure", {
                "return_code": completed.returncode,
            })
            raise HTTPException(502, "Piper synthesis failed; verify the voice model and local runtime.")
        if not output_path.is_file():
            raise HTTPException(502, "Piper completed without producing a WAV output.")
        if output_path.stat().st_size > _MAX_WAV_BYTES:
            raise HTTPException(413, "Generated speech exceeds the output size limit.")
        audio = output_path.read_bytes()
        if len(audio) < 12 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
            raise HTTPException(502, "Piper output is not a valid RIFF/WAVE file.")
        append_audit(settings.audit_path, "runtime.piper.synthesized", {
            "output_bytes": len(audio), "text_chars": len(req.text),
        })
        return Response(content=audio, media_type="audio/wav",
                        headers={"Content-Disposition": 'inline; filename="nova-speech.wav"'})
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(500, "Unable to safely stage or read local speech output.") from exc
    finally:
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass


def _convert_audio_to_wav(source_path: Path, target_path: Path, timeout: int) -> None:
    ffmpeg = _resolve_executable(settings.ffmpeg_cli_path, ("ffmpeg",))
    if not ffmpeg:
        raise HTTPException(503, "Non-WAV transcription requires local FFmpeg. Set NOVA_FFMPEG_CLI_PATH.")
    try:
        result = subprocess.run(
            [ffmpeg, "-nostdin", "-v", "error", "-y", "-i", str(source_path),
             "-map_metadata", "-1", "-vn", "-ac", "1", "-ar", "16000",
             "-sample_fmt", "s16", "-f", "wav", str(target_path)],
            shell=False, capture_output=True, text=True, timeout=timeout,
            check=False, cwd=str(source_path.parent),
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(504, "Local FFmpeg audio conversion timed out.") from exc
    if result.returncode != 0 or not target_path.is_file():
        raise HTTPException(415, "Local FFmpeg could not decode this audio format.")
    if target_path.stat().st_size > _MAX_WAV_BYTES:
        raise HTTPException(413, "Normalized WAV exceeds the 25 MB safety limit.")
    with target_path.open("rb") as stream:
        header = stream.read(12)
    if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
        raise HTTPException(502, "FFmpeg output is not a valid RIFF/WAVE file.")


@router.post("/whisper/transcribe")
async def transcribe_with_whisper(file: UploadFile = File(...)):
    """Transcribe common audio formats using local FFmpeg and whisper.cpp."""
    filename = Path(file.filename or "audio.wav").name
    suffix = Path(filename).suffix.lower()
    allowed_suffixes = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm", ".aac", ".mp4"}
    if suffix not in allowed_suffixes:
        await file.close()
        raise HTTPException(415, "Supported audio formats: WAV, MP3, M4A, FLAC, OGG, WebM, AAC and MP4.")
    executable = _resolve_executable(settings.whisper_cli_path, ("whisper-cli",))
    if not executable:
        await file.close()
        raise HTTPException(503, "whisper.cpp whisper-cli was not found. Set NOVA_WHISPER_CLI_PATH to its executable.")
    model = settings.whisper_model_path.expanduser()
    if not model.is_file():
        await file.close()
        raise HTTPException(503, "Whisper model is missing. Set NOVA_WHISPER_MODEL_PATH to a local ggml model file.")
    if model.suffix.lower() != ".bin":
        await file.close()
        raise HTTPException(422, "whisper.cpp model path must point to a .bin ggml model file.")

    limit = max(1024, min(settings.whisper_max_upload_bytes, _MAX_WAV_BYTES))
    audio = await file.read(limit + 1)
    await file.close()
    if not audio:
        raise HTTPException(400, "Uploaded audio file is empty.")
    if len(audio) > limit:
        raise HTTPException(413, f"Audio upload exceeds the configured {limit}-byte limit.")
    if suffix == ".wav" and (len(audio) < 12 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE"):
        raise HTTPException(415, "Uploaded WAV is not a valid RIFF/WAVE file.")

    workspace = settings.workspace.resolve()
    audio_dir = workspace / ".nova-audio"
    if audio_dir.is_symlink():
        raise HTTPException(403, "Audio work directory must not be a symbolic link.")
    audio_dir.mkdir(parents=True, exist_ok=True)
    if workspace not in audio_dir.resolve().parents:
        raise HTTPException(403, "Audio work directory must remain inside the NOVA workspace.")
    job_id = uuid.uuid4().hex
    input_path = audio_dir / f"{job_id}{suffix}"
    normalized_path = input_path if suffix == ".wav" else audio_dir / f"{job_id}-normalized.wav"
    output_prefix = audio_dir / f"{job_id}-transcript"
    output_path = Path(str(output_prefix) + ".txt")
    timeout = max(10, min(settings.whisper_timeout_seconds, 600))
    try:
        with input_path.open("xb") as stream:
            stream.write(audio)
        if suffix != ".wav":
            _convert_audio_to_wav(input_path, normalized_path, timeout)
        with normalized_path.open("rb") as stream:
            wav_header = stream.read(12)
        if len(wav_header) < 12 or wav_header[:4] != b"RIFF" or wav_header[8:12] != b"WAVE":
            raise HTTPException(415, "Input is not a valid WAV after local normalization.")
        normalized_bytes = normalized_path.stat().st_size
        if normalized_bytes > _MAX_WAV_BYTES:
            raise HTTPException(413, "Normalized audio exceeds the 25 MB safety limit.")
        command = [
            executable, "--model", str(model.resolve()), "--file", str(normalized_path),
            "-otxt", "-of", str(output_prefix), "-nt",
        ]
        try:
            completed = subprocess.run(
                command, shell=False, capture_output=True, text=True,
                timeout=timeout, check=False, cwd=str(workspace),
            )
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(504, "whisper.cpp transcription timed out.") from exc
        if completed.returncode != 0:
            append_audit(settings.audit_path, "runtime.whisper.failure", {
                "job_id": job_id, "return_code": completed.returncode,
            })
            raise HTTPException(502, "whisper.cpp transcription failed; verify the local runtime/model.")
        if not output_path.is_file():
            raise HTTPException(502, "whisper.cpp completed without producing the expected text output.")
        transcript = output_path.read_text(encoding="utf-8", errors="replace").strip()
        append_audit(settings.audit_path, "runtime.whisper.transcribed", {
            "job_id": job_id, "input_bytes": len(audio), "normalized_bytes": normalized_bytes,
            "source_format": suffix.lstrip("."), "converted": suffix != ".wav",
            "output_chars": len(transcript),
        })
        return {"runtime": "whisper.cpp", "model": model.name, "transcript": transcript,
                "input_bytes": len(audio), "source_format": suffix.lstrip("."),
                "converted": suffix != ".wav", "job_id": job_id}
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(500, "Unable to safely stage or read local transcription files.") from exc
    finally:
        for path in {input_path, normalized_path, output_path}:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
