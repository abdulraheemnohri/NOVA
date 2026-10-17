# NOVA — Neural Offline Verified Agent

Local-first agent workbench with LiteRT-LM-only chat inference, default-deny tool policy, approval-gated writes, bearer-token-protected local API routes, and tamper-evident audit records.

## Status

NOVA is an active engineering project, not yet a feature-complete production release. CI covers the backend tests and frontend tests/build, but target-machine LiteRT-LM compatibility, optional speech binaries/models, and security smoke tests still require validation on the actual host.

## Debian quick start

The setup helper installs system prerequisites, creates a Python virtual environment, installs backend dependencies, and installs the Web UI dependencies. It does not install Docker or download model weights.

```bash
bash scripts/setup_debian.sh
```

Start the backend in one terminal and the Web UI in another:

```bash
bash scripts/run_backend.sh
bash scripts/run_frontend.sh
```

Open `http://127.0.0.1:5173`. On first startup NOVA creates `data/api.token` with restrictive permissions. Read it locally and paste it into the Web UI sign-in screen. Never share the token. Keep the backend bound to loopback.

See [Development and Scripts](docs/DEVELOPMENT.md) for manual setup, dependency files, diagnostics, tests, packaging and optional runtime setup.

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

NOVA never falls back to Ollama, llama.cpp, or cloud providers. The default endpoint is `http://127.0.0.1:9379/v1`; override it with `NOVA_LITERT_BASE_URL` if the local server uses another loopback port. Start the local server with the command supported by your installed LiteRT-LM version. Confirm its CLI options against that version; NOVA does not automatically install or launch an inference server.

## Task planner and queue

The Tasks page stores local operator-authored tasks, plan steps, priority, optional timezone-aware due times, status transitions, attempt counts and results in SQLite. Every create/status/delete event is audit logged. The queue does not execute shell commands or model-generated plans, and due times are not scheduled until a dedicated worker is implemented. See `docs/TASKS_API.md`.

## Mobile / Android system monitoring

The System Monitor includes a best-effort Android profile when NOVA runs in an Android-compatible Python environment such as Termux. It can read CPU core frequencies, RAM, the storage volumes accessible to the process, battery status from Android sysfs or optional Termux:API, and selected Adreno/Mali GPU counters. Enable Termux shared-storage permission if you want the shared storage volume to appear. Android OEM kernels often restrict GPU/NPU/TPU counters; missing values are reported as unavailable rather than guessed. This is telemetry only and does not alter performance, battery, thermal, or device settings.

## Settings

The Settings page persists a small, validated preference set in local SQLite: chat output-token limit, optional dashboard auto-refresh interval, and model-selection confirmation. Security-critical settings remain read-only and environment-controlled. Preference changes are audit-logged. See `docs/API.md` for the settings endpoints.

## Runtime diagnostics

Open **Diagnostics** in the dashboard or call `GET /api/diagnostics` with the local bearer token. It reports LiteRT-LM endpoint reachability, model IDs returned by the local server, whether the configured model ID appears in that list, CLI presence on `PATH`, host/Python/disk details and audit-chain status. It is read-only: it does not execute shell commands or guess runtime versions, model compatibility, or GPU/NPU support. A model appearing in `/models` is not proof that inference will succeed.

## Local model runtimes and speech

The **Runtimes** page inventories LiteRT-LM, whisper.cpp, Piper, ONNX Runtime, TensorFlow Lite/LiteRT Python packages, llama.cpp and Transformers. LiteRT-LM remains the only chat runtime; optional runtimes are task-scoped and never silent fallbacks. Local whisper.cpp WAV transcription is available through `POST /api/runtimes/whisper/transcribe`; Piper WAV synthesis is available through `POST /api/runtimes/piper/synthesize`. ONNX/TFLite model execution remains discovery-only until task-specific adapters are implemented. Setup, environment variables, security boundaries and model licensing notes are in `docs/MODEL_RUNTIMES.md`.

## Security and current limits

- Default-deny tool policy; unknown tools are blocked.
- Workspace writes and destructive rollback require explicit, payload-bound approval.
- All API routes except `/api/health` require a local bearer token.
- Audit JSONL records use a SHA-256 hash chain. This is tamper-evident, not immutable against a privileged administrator.
- Filesystem paths are confined to the configured workspace.
- Authentication is a single local operator token, not multi-user RBAC.
- Full semantic RAG, background scheduler/worker, production-grade process sandboxing, broader vision/OCR adapters, multi-user RBAC, and crash-recovery orchestration remain incomplete.

Read `docs/SECURITY.md`, `docs/ARCHITECTURE.md`, `docs/OFFLINE_DEPLOYMENT.md`, and `docs/ROADMAP.md`.
