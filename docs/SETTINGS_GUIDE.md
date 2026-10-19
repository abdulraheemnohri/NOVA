# NOVA Settings, Model Sizing and Troubleshooting Guide

This guide explains the visible Settings page, which values are editable, which values require a local environment-file change, and how to diagnose model and runtime problems. NOVA is local-first; chat inference is LiteRT-LM-only. Model Hub search/downloads need internet access, but downloaded artifacts remain in the local cache.

## 1. Quick safety rules

- Keep the API bound to `127.0.0.1`; do not expose it directly to a LAN or the public internet.
- The first-run API token is stored in `data/api.token` (or the path selected by `NOVA_API_TOKEN_FILE`). Treat it as a password.
- Never commit a real `.env`, Hugging Face token, API token, or private model weights.
- NOVA does not execute code from downloaded model repositories and does not silently fall back to cloud chat, Ollama, or llama.cpp.
- A model listed by `/v1/models` is not proof that its weights are loaded or that inference succeeds. Run a short test prompt and inspect Diagnostics/runtime logs.
- Model activation is a selection/availability flag; it does not itself load or unload weights or stop a LiteRT-LM process.

## 2. Settings page: what each section does

### Operator preferences

| Setting | Allowed range / choices | What it changes | Guidance |
|---|---|---|---|
| Chat response token limit | 64–4096 tokens | Maximum output tokens requested for a chat turn | Start at 256–512 on constrained devices. Larger output can increase latency and memory pressure. |
| Chat temperature | 0.0–1.5 | Sampling variation sent to the model runtime | Use 0.0–0.3 for predictable troubleshooting; higher values may produce more variation. Runtime/model behavior can differ. |
| Automatic status refresh | Disabled, 15, 30, 60, 120, or 300 seconds | Polling cadence for status panels | Keep disabled or use 30–60 seconds on slow devices. A zero value disables this preference's refresh loop; individual pages may have their own status refresh behavior. |
| Confirm model changes | On/off | Adds confirmation before changing the registered chat model | Leave on unless you intentionally want faster model switching. Confirmation is not a compatibility test. |

These preferences are stored in local SQLite and audit-logged. Use **Save preferences** to persist them.

### Runtime feature switches

- **Local retrieval:** permits the local keyword/document retrieval feature. It is not semantic vector search.
- **Model Hub:** enables Hugging Face model search and file metadata inspection.
- **Model downloads:** enables explicit artifact downloads. Keep disabled when you only need offline operation.
- **Whisper.cpp, Piper, OCR and ONNX Runtime:** enable requests/discovery for the corresponding optional local task runtimes. A switch does not install a package, download a model, or prove the runtime is configured.
- **Maximum model download size (GB):** sets a per-artifact upper limit. The backend validates this setting and clamps it to the environment hard cap. It does not limit total cache size or the model's RAM use.

Feature switches are saved in SQLite and audit-logged. The environment setting `NOVA_HUGGINGFACE_MAX_DOWNLOAD_BYTES` defines the hard maximum; the UI cannot raise the limit above it.

### AI capability access

These human-controlled toggles govern whether the model may request registered tools, use active skills, draft skills, propose bounded tools, or request supported runtime operations. They do not bypass allowlists, validation, approval gates or audit logging. Generated skills remain drafts; generated tool code is not executed.

**Project settings access is permanently human-only.** The AI cannot change authentication, network policy, write approval policy, project configuration, or its own capability switches.

### Live status and backend configuration inventory

The live snapshot reports observed runtime connectivity, inventory, audit-chain status and AI/tool counts. The environment-managed configuration inventory is read-only and omits secret values and raw launch commands.

To change environment-managed values, edit the local `.env` file and restart the backend. Use the relevant Diagnostics page after restarting. Never paste secrets into screenshots, issues or logs.

## 3. Model download sizes and GB units

NOVA uses **decimal GB** for download limits:

- 1 GB = 1,000,000,000 bytes.
- 20 GB = 20,000,000,000 bytes (the default hard cap).
- A setting may be lowered below the hard cap, but cannot raise it.
- A per-request limit can only lower the saved effective limit; it cannot bypass it.
- NOVA checks repository metadata before downloading, checks the response Content-Length when present, counts bytes while streaming, verifies the final size against metadata, checks available storage, reserves 256 MiB of free space, writes to a temporary file and atomically moves the verified result into the cache.
- Failed/incomplete downloads are discarded and successful artifacts are SHA-256 hashed and audit-logged.
- The limit applies to each artifact, not the total cache. Check the cache inventory and free storage before downloading multiple models.

### Model file size is not RAM usage

A downloaded model's disk size is only one part of its runtime memory requirement. Runtime overhead, tokenizer and metadata, context/KV cache, temporary buffers, quantization and accelerator memory affect actual use. Check the model's upstream documentation and test on the target device before selecting it for chat.

| Device profile | Approximate physical RAM | Conservative approach |
|---|---:|---|
| Low-end / constrained | Up to 4 GB | One small quantized model, short context, CPU-first; keep substantial RAM free for the OS. |
| Mid-range | 4–8 GB | One modest model; monitor free RAM and latency before increasing context. |
| High-end / workstation | 8 GB and above | Larger models may fit, but verify actual RAM/VRAM, context and LiteRT-LM support. |

These are planning tiers, not guarantees or automatic eligibility checks. A 4 GB artifact does **not** mean it needs only 4 GB RAM. Prefer a known compatible `.litertlm` artifact for chat. `.gguf`, `.tflite`, `.onnx` and `.safetensors` downloads are inventory-only unless a task-specific adapter is implemented.

### Change the hard download cap

1. Stop the NOVA backend.
2. Back up your private local `.env` file.
3. Set `NOVA_HUGGINGFACE_MAX_DOWNLOAD_BYTES` to the desired byte count, never above `20000000000` by default.
4. Restart the backend.
5. Open Settings and confirm the displayed cap. The saved runtime feature limit may still be lower; raise it only up to the environment hard cap.
6. Check available storage in the Model Hub/cache status before starting a download.

Examples:
- 2 GB: `NOVA_HUGGINGFACE_MAX_DOWNLOAD_BYTES=2000000000`
- 8 GB: `NOVA_HUGGINGFACE_MAX_DOWNLOAD_BYTES=8000000000`
- 20 GB: `NOVA_HUGGINGFACE_MAX_DOWNLOAD_BYTES=20000000000`

A configured cap of zero disables positive-size downloads through validation; use the Model Downloads feature switch to turn downloads off clearly.

## 4. Environment-managed settings

The repository's `.env.example` lists the current environment variables and safe example values. The most relevant settings include:

| Variable | Purpose |
|---|---|
| `NOVA_WORKSPACE` | Workspace root for files handled by NOVA. |
| `NOVA_DATABASE_PATH` | Local SQLite database path. |
| `NOVA_AUDIT_PATH` | Audit JSONL file path. |
| `NOVA_API_TOKEN_FILE` | Private local API bearer-token file path. |
| `NOVA_LITERT_BASE_URL` | Local LiteRT-LM-compatible OpenAI-style API base URL; default is `http://127.0.0.1:9379/v1`. |
| `NOVA_LITERT_MODEL` | Configured model ID expected by the local endpoint. |
| `NOVA_LITERT_CHAT_TIMEOUT_SECONDS` | Chat request timeout (5–600 seconds; default 120). |
| `NOVA_HUGGINGFACE_CACHE_DIR` | Local artifact cache path. |
| `NOVA_HUGGINGFACE_MAX_DOWNLOAD_BYTES` | Hard per-artifact download ceiling in bytes (default 20,000,000,000). |
| `NOVA_HUGGINGFACE_TOKEN` | Optional token for gated/private repositories. Prefer the local token UI/file where supported; never commit it. |
| `NOVA_REQUIRE_APPROVAL_FOR_WRITES` | Environment-controlled write-approval policy. |
| `NOVA_SCHEDULER_ENABLED`, `NOVA_SCHEDULER_INTERVAL_SECONDS` | Optional scheduler; due tasks move to Planned for operator review and do not execute generated commands. |
| `NOVA_SEMANTIC_RETRIEVAL_ENABLED`, `NOVA_EMBEDDING_MODEL_PATH` | Optional semantic retrieval configuration; disabled by default until a compatible local embedding model is installed. |
| `NOVA_WHISPER_CLI_PATH`, `NOVA_WHISPER_MODEL_PATH`, `NOVA_PIPER_CLI_PATH`, `NOVA_PIPER_MODEL_PATH` | Optional local speech runtime executable/model paths. |
| `NOVA_TESSERACT_CLI_PATH`, `NOVA_OCR_TIMEOUT_SECONDS`, `NOVA_OCR_MAX_UPLOAD_BYTES` | Local OCR executable and bounded request settings. |
| `NOVA_PDF_OCR_ENABLED`, `NOVA_PDF_RENDERER_CLI_PATH`, `NOVA_PDF_OCR_MAX_PAGES` | Optional scanned-PDF OCR configuration. |
| `NOVA_FFMPEG_CLI_PATH` | Optional local audio conversion executable. |

For the complete current list, comments and example paths, consult [`.env.example`](../.env.example). Environment values are loaded when the backend starts. Do not expose raw environment files or add secrets to issue reports.

## 5. Troubleshooting checklist

### Chat returns a connection or timeout error

1. Confirm the LiteRT-LM server is running and bound to loopback.
2. Check `NOVA_LITERT_BASE_URL` and `NOVA_LITERT_MODEL`.
3. Test `GET /v1/models` and a short `POST /v1/chat/completions` directly against the local endpoint.
4. Open NOVA Diagnostics and compare the configured model ID with the endpoint's advertised IDs.
5. If direct inference succeeds but NOVA chat fails, check backend logs and the configured chat timeout. Do not assume a model advertised by the endpoint is loaded.
6. A `BrokenPipeError` can occur when a client disconnects or cancels a request while a response is being written. The log alone does not prove that the model crashed; reproduce with the UI left open and compare with a direct request.

### Download rejected

- Check the effective GB limit in Settings and the hard cap in `.env`.
- Verify that the exact repository revision lists the selected artifact and its size.
- Check free disk space. NOVA intentionally keeps a 256 MiB reserve.
- Gated/private repositories require valid local access. Do not paste the token into chat or logs.
- Only the listed supported artifact extensions can be downloaded. Downloads are explicit and never run repository code.

### A model is not selectable or chat fails

- Confirm the artifact is registered and its format is `.litertlm`.
- Check that the model is enabled and run model compatibility preflight.
- Verify the local server can actually load the file and advertises the expected model ID.
- Use a short prompt first. Reduce output tokens or context if memory pressure is suspected.
- Do not deactivate the configured fallback model without understanding the consequences.

### Audit/security warning

Stop risky operations, review the local audit file and use Diagnostics to verify the chain. Do not delete or edit audit records to silence a warning. Keep API and Hub tokens private.

## 6. Useful references

- [README and quick start](../README.md)
- [API reference](API.md)
- [Architecture](ARCHITECTURE.md)
- [Security controls](SECURITY_CONTROLS.md)
- [Offline deployment](OFFLINE_DEPLOYMENT.md)
- [Model runtimes](MODEL_RUNTIMES.md)
- [Real-device testing](REAL_DEVICE_TESTING.md)
