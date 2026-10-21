# Local model runtimes

NOVA supports multiple *task-scoped* local runtimes, not a universal model runner. **LiteRT-LM remains the only runtime used for chat inference.** A detected executable is not proof that a model or accelerator is compatible.

## Runtime inventory

The authenticated `GET /api/runtimes` endpoint and the **Runtimes** UI page report whether these engines/packages are visible:

| Runtime | Intended task | Current integration |
|---|---|---|
| LiteRT-LM | Chat and reasoning | Existing primary chat adapter |
| whisper.cpp | Offline speech-to-text | Implemented WAV transcription endpoint |
| Piper | Local text-to-speech | Implemented WAV synthesis endpoint using local executable and voice model |
| ONNX Runtime | Compatible ONNX models for embeddings, OCR, audio and classification | Package detection only; task adapters pending |
| TensorFlow Lite / LiteRT Python packages | Edge vision/audio/classification | Package detection only; task adapters pending |
| llama.cpp | GGUF model serving | Optional binary detection only; not used for NOVA chat |
| Hugging Face Transformers | Specialized local model pipelines | Package detection only; not loaded automatically |

No runtime server is automatically launched and no alternate chat backend is selected when LiteRT-LM is unavailable.

## whisper.cpp setup (Debian/Linux)

Follow the upstream build instructions at <https://github.com/ggml-org/whisper.cpp>. A typical source build is:

```bash
sudo apt install -y git cmake build-essential
git clone https://github.com/ggml-org/whisper.cpp.git
cd whisper.cpp
cmake -B build
cmake --build build -j --config Release
```

Obtain a Whisper GGML model using the upstream model documentation and place it in NOVA's local model directory. For example, from the whisper.cpp checkout:

```bash
sh ./models/download-ggml-model.sh base
mkdir -p /path/to/NOVA/data/models/whisper
cp models/ggml-base.bin /path/to/NOVA/data/models/whisper/ggml-base.bin
```

Set the paths in NOVA's backend environment (not the browser):

```dotenv
NOVA_WHISPER_CLI_PATH=/absolute/path/to/whisper.cpp/build/bin/whisper-cli
NOVA_WHISPER_MODEL_PATH=/absolute/path/to/NOVA/data/models/whisper/ggml-base.bin
NOVA_WHISPER_TIMEOUT_SECONDS=180
NOVA_WHISPER_MAX_UPLOAD_BYTES=25000000
```

Restart the backend, open **Runtimes**, and check that both the executable and model artifact are detected. The endpoint `POST /api/runtimes/whisper/transcribe` accepts a multipart field named `file`, requires a `.wav` RIFF/WAVE file, limits upload size and runtime duration, and returns a transcript. The adapter accepts WAV directly and supports MP3, M4A, FLAC, OGG, WebM, AAC and MP4 through an explicitly installed local FFmpeg executable. Set `NOVA_FFMPEG_CLI_PATH` if it is not on PATH. Converted files are normalized to 16 kHz mono signed 16-bit PCM WAV with `shell=False`, bounded size/time, and temporary workspace-local files. No audio is sent to a remote service.

## Piper TTS

Upstream project and usage: <https://github.com/ggml-org/whisper.cpp> for ASR and <https://github.com/OHF-Voice/piper1-gpl> / <https://github.com/rhasspy/piper> for Piper distributions and voice licensing. Install a compatible local Piper executable and voice `.onnx` plus its metadata sidecar. Configure `NOVA_PIPER_CLI_PATH` and `NOVA_PIPER_MODEL_PATH`. The authenticated `POST /api/runtimes/piper/synthesize` endpoint accepts JSON `{ "text": "..." }` and returns a bounded `audio/wav` response. The Runtimes UI provides text input and local playback. Synthesis runs with `shell=False`, a bounded timeout and a workspace-local temporary output that is removed after the audio is read.

Review each voice/model's license and redistribution conditions before using or packaging it.

## ONNX Runtime and edge model packages

ONNX Runtime installation options are documented at <https://onnxruntime.ai/docs/install/>. CPU deployments commonly use:

```bash
python -m pip install onnxruntime
```

Install only the provider package appropriate for the device and driver stack. Do not install CPU and GPU variants together in the same Python environment unless upstream compatibility guidance explicitly permits it. NOVA currently detects ONNX Runtime but does not yet execute arbitrary ONNX models.

TensorFlow Lite/LiteRT Python packages are also detected if installed. Actual model execution requires a task-specific adapter and tests for each model's input/output signature.

## Security and compatibility

- Model files are local artifacts; runtime discovery never downloads or executes model repositories.
- whisper.cpp is launched with a fixed argument list using `shell=False`, a bounded timeout and a workspace-local temporary directory. The uploaded file is deleted after processing.
- Only WAV extension plus RIFF/WAVE header is checked; users should provide trusted audio and correct PCM encoding.
- Model compatibility, language quality, RAM use, hardware acceleration and licensing are not inferred from detection.
- Do not expose NOVA's API beyond loopback without a separate hardened deployment design.


## Local image OCR

The explicit `POST /api/runtimes/ocr/extract` adapter uses a preinstalled Tesseract executable and optional Pillow. It accepts PNG, JPEG, TIFF, BMP and WebP, enforces upload/dimension/output limits, normalizes images into a temporary workspace directory, calls the executable with `shell=False` and a timeout, cleans temporary files and emits an audit event. OCR is task-scoped and never a chat fallback. Install Tesseract and Pillow yourself; NOVA does not download models or binaries automatically.


## Optional offline semantic/hybrid retrieval

Keyword retrieval remains the default. To enable local embedding-assisted retrieval, install the optional dependency set with `pip install -r requirements-optional.txt`, place a compatible SentenceTransformers model directory at `./data/models/embeddings` (or configure `NOVA_EMBEDDING_MODEL_PATH`), and set `NOVA_SEMANTIC_RETRIEVAL_ENABLED=true` in the backend environment. The model must already exist locally: NOVA passes `local_files_only=True`, uses CPU embeddings, and does not download model files. Search blends normalized lexical overlap (45%) and cosine similarity (55%); the score is a ranking signal, not calibrated confidence. The initial adapter scans at most 5,000 chunks per semantic query and does not yet persist vector indexes. If the model or optional library is unavailable, search falls back to keyword retrieval. Inspect the returned source IDs and excerpts before relying on generated claims.
## Model Manager and download lifecycle

The **Models** page combines the curated catalog, local SHA-256 registry, active LiteRT-LM model selection, Hugging Face Hub search, repository file inspection, and explicit artifact download. Downloads are constrained by `NOVA_HUGGINGFACE_MAX_DOWNLOAD_BYTES` (default 20,000,000,000 bytes (20 GB decimal)), written to a temporary file, size-checked while streaming, and atomically moved into the cache only after the download completes. Cache hits are also checked against the current configured size cap and repository metadata when a size is available. The Models/Settings UI displays the limit in decimal GB, while the API stores exact bytes. The environment variable remains the hard ceiling; a lower configured value always wins. Before a new download, NOVA verifies that the model cache volume has the artifact size plus a 256 MiB safety reserve available and rechecks free space during streaming. The status endpoint reports total/free cache-volume capacity and cache usage without exposing secrets. The SHA-256 is calculated locally and the UI registers the resulting file in the local model inventory.

A file extension is not proof of compatibility or safety. Downloaded artifacts are not executed by NOVA. Only registered `.litertlm` files are eligible for chat selection; runtime/model compatibility must still be verified on the target device. Respect each model's license and access conditions.

## Runtime inventory and versions

The **Runtimes** page reports local executable/model presence and LiteRT-LM endpoint reachability. For optional Python runtimes, it also displays the installed package version when distribution metadata is available; version discovery does not import or execute the model runtime. Detection is not an installation manager: NOVA does not install, update, start, or uninstall runtimes automatically. Install and update optional packages using the documented upstream instructions for your OS, then refresh the inventory. No discovered runtime is substituted for LiteRT-LM chat inference.

## Runtime setup preflight

The authenticated read-only `GET /api/runtimes/preflight` endpoint summarizes the current inventory into actionable setup checks. It marks LiteRT-LM reachability as the primary-chat readiness gate and offers optional next steps for speech, OCR, FFmpeg, ONNX and edge runtimes. The Runtimes page displays these checks. Preflight never installs packages, downloads models, executes runtime binaries, changes settings or switches the primary chat runtime.

## Runtime operations: package previews

The authenticated `POST /api/runtimes/operations/preview` endpoint currently supports read-only Debian/Ubuntu previews for FFmpeg and Tesseract/Pillow. It accepts runtime IDs from a strict allowlist and returns a fixed package list and command for operator review. Unsupported IDs are rejected. No shell or package manager is invoked, no installation occurs, and the operator must review package sources and execute any approved command manually. Whisper.cpp, Piper, and model runtimes retain their upstream-specific setup instructions.

## Runtime installation approval ledger

The authenticated `POST /api/runtimes/operations/requests` endpoint creates a persistent, pending request for one of the strictly allowlisted Debian package plans. `GET /api/runtimes/operations/requests` lists recent requests, and `POST /api/runtimes/operations/requests/{request_id}/decision` records an explicit `approve` or `reject` decision. Decisions are atomic, terminal, and audit logged; duplicate decisions return a conflict. Request contents are stored in the configured local NOVA SQLite database.

**Approval is bookkeeping, not execution.** Even an approved request never invokes `sudo`, `apt-get`, a shell, or any package manager. The queue exposes a fixed command for operator review, and the operator remains responsible for reviewing and running it manually. Unsupported runtime IDs are rejected; arbitrary package names or commands cannot be submitted.


## Restricted package installation execution

The execution endpoint is disabled unless the backend environment explicitly sets `NOVA_RUNTIME_INSTALL_EXECUTION_ENABLED=true`. Keep this disabled on ordinary deployments. Enabling it permits the backend process to invoke the system package manager, so it must only be considered in a dedicated, isolated local deployment after reviewing the threat model; do not run the entire NOVA web/API service as root just to enable this feature.

Execution requires a previously approved request plus a second confirmation that exactly matches its request ID. The endpoint revalidates the stored package list against the runtime allowlist, uses an argument array with `shell=False`, invokes only the resolved `apt-get` binary, has a 600-second timeout, uses a restricted environment, and permits at most one execution record per request. The execution log records status, exit code, bounded output, timestamps, and recovery guidance. A timeout or failure does not trigger automatic package removal or rollback; inspect the logs and package state manually. The execution path has not been exercised against a real system package manager as part of repository editing.


## Automatic local model discovery and hardware-aware profiles

Opening **Model Manager** triggers a bounded scan of NOVA's configured Hugging Face cache and `./data/models`. The scan recognizes `.litertlm`, `.gguf`, `.tflite`, `.onnx`, `.safetensors`, and `.bin` artifacts, calculates SHA-256 for newly discovered files, and records them in the local registry. It scans at most 10,000 file entries and registers at most 200 new artifacts per pass. Repeated scans skip registered paths. Discovery does not download, execute, activate, or prove compatibility of a model. Only `.litertlm` artifacts are eligible for NOVA chat selection; other formats are inventory-only until a compatible task adapter exists.

The device profile endpoint reads host RAM from Linux `/proc/meminfo` or Windows `GlobalMemoryStatusEx` where available. The low-end profile is up to 4 GiB RAM, mid-range is over 4 through 8 GiB, and high-end is over 8 GiB. The conservative budget is an advisory 60% of currently available RAM, not a prediction of exact model fit. GPU/VRAM is reported as unknown when reliable cross-platform detection is unavailable. Always account for model quantization, context/KV cache, runtime overhead and other running processes.


## Model compatibility preflight

The read-only `GET /api/models/preflight/{model_id}` endpoint checks activation state, chat-runtime format eligibility, local artifact presence, registered SHA-256 integrity, and advisory available-memory guidance. It returns explicit blockers and warnings. It does not download, activate, load, or execute artifacts. A passing preflight is not proof that the installed LiteRT-LM build can load a particular model; verify that on the target device.


## On-demand runtime lifecycle controller

NOVA's task-scoped Whisper, Piper, FFmpeg and Tesseract invocations use the allowlisted runtime lifecycle manager in `backend/nova/runtime_lifecycle.py`. It validates the executable against a fixed runtime ID, rejects shell execution, enforces bounded timeouts, tracks start/stop/failure timestamps and limits concurrent managed tasks. `GET /api/runtimes/lifecycle` reports active tasks and recent event metadata without command arguments, prompt text or file contents. Task executables run only when a corresponding task endpoint is called and exit after the task; no optional task runtime is kept resident while idle.

Configure `NOVA_RUNTIME_PROFILE=mobile` for one managed runtime at a time, `balanced` for two, or `performance` for three. The mobile Debian installer selects the mobile profile. LiteRT-LM is the primary chat service and remains separate; NOVA never silently switches chat inference to an optional runtime. The model may request only registered task capabilities; it cannot launch arbitrary executables or shell commands.

For Android phones running Debian, use [Mobile Debian installation](MOBILE_DEBIAN.md). The default installer installs core NOVA plus FFmpeg/Tesseract/Pillow. Add `--with-litert-lm`, `--with-whisper-cpp`, `--with-piper`, or `--with-onnx` only for the task capabilities you need; `--all-runtimes` installs all supported optional tools but does not download model weights or voice files.
