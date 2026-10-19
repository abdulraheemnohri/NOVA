# NOVA — Neural Offline Verified Agent

Local-first agent workbench with LiteRT-LM-only chat inference, default-deny tool policy, approval-gated writes, bearer-token-protected local API routes, and tamper-evident audit records.

## Status

NOVA is an active engineering project, not yet a feature-complete production release. CI covers the backend tests and frontend tests/build, but target-machine LiteRT-LM compatibility, optional speech binaries/models, and security smoke tests still require validation on the actual host.

## Quick start (Windows, Linux and macOS)

The cross-platform installer discovers all project requirements*.txt files, creates an isolated Python environment, installs backend and Web UI dependencies, installs the LiteRT-LM CLI by default, and installs supported system tools (Node.js/npm, FFmpeg and Tesseract OCR) through the platform package manager. It does not install Docker, start a model server, or download model weights. Use --dry-run to preview changes, --skip-system-runtimes to skip OS packages, or --skip-litert-lm to skip the LiteRT-LM CLI package.

```bash
python scripts/install_all.py

# Optional task runtimes, installed only when requested
python scripts/install_optional_runtimes.py --piper
# Build whisper.cpp only when you need offline transcription (requires a pinned release tag)
python scripts/install_optional_runtimes.py --whisper-cpp --whisper-tag v1.7.6
```

Start the backend in one terminal and the Web UI in another:

```bash
bash scripts/run_backend.sh
bash scripts/run_frontend.sh
```

Open `http://127.0.0.1:5173`. On first startup NOVA creates `data/api.token` with restrictive permissions. Read it locally and paste it into the Web UI sign-in screen. Never share the token. Keep the backend bound to loopback.

See [Development and Scripts](docs/DEVELOPMENT.md) for manual setup, dependency files, diagnostics, tests, packaging and optional runtime setup. For model acquisition, configuration, offline setup and the full target-device smoke-test matrix, follow [Real-device installation and release validation](docs/REAL_DEVICE_TESTING.md).

## Dependency files

- `requirements.txt`: core Python backend dependencies.
- `requirements-dev.txt`: core dependencies plus backend test/lint tools.
- `requirements-optional.txt`: optional ONNX/document/image libraries for task-specific adapters.
- `frontend/package.json`: Web UI dependencies.

The dependency lists are intentionally separated so a basic install does not pull in optional task engines. Python dependencies can be installed with `python -m pip install -r requirements-dev.txt`.

## Hugging Face Hub support

The Model Manager includes a dedicated Hugging Face page for model metadata search, repository file inspection, and explicit downloads of `.litertlm`, `.gguf`, `.tflite`, `.onnx`, and `.safetensors` artifacts. Downloads are size-limited, written atomically to the local cache, SHA-256 hashed, registered locally, and audit-logged. This feature requires internet access only when searching/downloading; cached files remain local. NOVA never sends prompts to Hugging Face and never executes downloaded repository code. Only a registered LiteRT-LM artifact can be selected for chat; other formats remain inventory-only until an adapter is implemented.

Optional settings: `NOVA_HUGGINGFACE_CACHE_DIR`, `NOVA_HUGGINGFACE_MAX_DOWNLOAD_BYTES`, and `NOVA_HUGGINGFACE_TOKEN` (backend environment only; needed for gated/private repositories). Never commit a real token. See `docs/ARCHITECTURE.md` and `docs/OFFLINE_DEPLOYMENT.md`.

## LiteRT-LM

NOVA never falls back to Ollama, llama.cpp, or cloud providers. The default endpoint is `http://127.0.0.1:9379/v1`; override it with `NOVA_LITERT_BASE_URL` if the local server uses another loopback port. The unified installer installs the LiteRT-LM CLI package by default, but it does not start the inference server or download model weights. Configure the server command supported by your installed LiteRT-LM version and verify its CLI options before enabling autostart.

## Local knowledge-assisted chat

Chat performs a bounded local keyword search over indexed document chunks and returns the matching source names/chunk IDs alongside the answer. Retrieved document text is labeled as untrusted reference material. This is lexical retrieval, not semantic vector search, and the model may still generate unsupported claims; review source metadata before relying on results.

## Task planner and queue

The Tasks page stores local operator-authored tasks, plan steps, priority, optional timezone-aware due times, status transitions, attempt counts and results in SQLite. Every create/status/delete event is audit logged. The queue does not execute shell commands or model-generated plans. The opt-in local scheduler can move due tasks to Planned for operator review; it does not execute task plans. See `docs/TASKS_API.md`.

## Mobile / Android system monitoring

The System Monitor includes a best-effort Android profile when NOVA runs in an Android-compatible Python environment such as Termux. It can read CPU core frequencies, RAM, the storage volumes accessible to the process, battery status from Android sysfs or optional Termux:API, and selected Adreno/Mali GPU counters. Enable Termux shared-storage permission if you want the shared storage volume to appear. Android OEM kernels often restrict GPU/NPU/TPU counters; missing values are reported as unavailable rather than guessed. This is telemetry only and does not alter performance, battery, thermal, or device settings.

## Settings

The Settings page includes operator preferences, runtime feature switches, AI capability controls, live status, an effective non-secret configuration inventory, and inline safety guidance. Model download limits are displayed in decimal GB (1 GB = 1,000,000,000 bytes), with the backend enforcing the lower of the saved limit and `NOVA_HUGGINGFACE_MAX_DOWNLOAD_BYTES`. See [the complete Settings and model sizing guide](docs/SETTINGS_GUIDE.md) for every editable/read-only setting, environment configuration, recommended model-size tiers, and troubleshooting steps.

The Settings page persists a small, validated preference set in local SQLite: chat output-token limit, optional dashboard auto-refresh interval, and model-selection confirmation. Security-critical settings remain read-only and environment-controlled. Preference changes are audit-logged. See `docs/API.md` for the settings endpoints.

## Token-aware terminal API helper

Use `bash scripts/nova-api.sh METHOD /api/path [JSON_BODY]` for terminal API calls. The helper reads `data/api.token` automatically, restricts requests to loopback addresses, and avoids placing the bearer token in shell history or process arguments. Examples and input rules are in [Development and Scripts](docs/DEVELOPMENT.md). The Web UI still uses its sign-in token flow.

## Runtime diagnostics

Open **Diagnostics** in the dashboard or call `GET /api/diagnostics` with the local bearer token. It reports LiteRT-LM endpoint reachability, model IDs returned by the local server, whether the configured model ID appears in that list, CLI presence on `PATH`, host/Python/disk details and audit-chain status. It is read-only: it does not execute shell commands or guess runtime versions, model compatibility, or GPU/NPU support. A model appearing in `/models` is not proof that inference will succeed.

## Local model runtimes and speech


### Installation command previews

The Runtimes page can display fixed, allowlisted Debian/Ubuntu commands for supported optional tools (currently FFmpeg and Tesseract OCR with Pillow). NOVA never executes `apt`, `apt-get`, `sudo`, shell commands, or package installations, even if the legacy `NOVA_RUNTIME_INSTALL_EXECUTION_ENABLED` environment variable is set. Copy a reviewed command and run it manually in your own terminal. Whisper.cpp and Piper require upstream binaries and compatible model/voice files, so NOVA does not invent a generic apt command for them.

The **Runtimes** page inventories LiteRT-LM, whisper.cpp, Piper, ONNX Runtime, TensorFlow Lite/LiteRT Python packages, llama.cpp and Transformers. LiteRT-LM remains the only chat runtime; optional runtimes are task-scoped and never silent fallbacks. Local whisper.cpp WAV transcription is available through `POST /api/runtimes/whisper/transcribe`; Piper WAV synthesis is available through `POST /api/runtimes/piper/synthesize`. ONNX/TFLite model execution remains discovery-only until task-specific adapters are implemented. Setup, environment variables, security boundaries and model licensing notes are in `docs/MODEL_RUNTIMES.md`.

## Security and current limits

- Default-deny tool policy; unknown tools are blocked.
- Workspace writes and destructive rollback require explicit, payload-bound approval.
- All API routes except `/api/health` require a local bearer token.
- Audit JSONL records use a SHA-256 hash chain. This is tamper-evident, not immutable against a privileged administrator.
- Filesystem paths are confined to the configured workspace.
- Authentication is a single local operator token, not multi-user RBAC.
- Full semantic RAG, production-grade process sandboxing, broader vision/OCR adapters, multi-user RBAC, and broader autonomous crash-recovery orchestration remain incomplete. Bounded recovery is implemented: interrupted runs are marked for operator review and are never replayed automatically.

Read `docs/SECURITY.md`, `docs/ARCHITECTURE.md`, `docs/OFFLINE_DEPLOYMENT.md`, and `docs/ROADMAP.md`.


## Optional WhatsApp third-party agents
NOVA can bridge a WhatsApp Business Cloud API webhook to up to five explicitly configured HTTPS agent endpoints. This is **not** the limited consumer WhatsApp app's agent-linking feature. See [WhatsApp bridge setup](docs/WHATSAPP_SETUP.md) for Meta credentials, sender allowlisting, webhook verification, token environment variables, and the encryption/privacy boundary. The bridge is disabled until credentials, allowed senders, and agent endpoints are configured.
