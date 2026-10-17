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

Restart the backend, open **Runtimes**, and check that both the executable and model artifact are detected. The endpoint `POST /api/runtimes/whisper/transcribe` accepts a multipart field named `file`, requires a `.wav` RIFF/WAVE file, limits upload size and runtime duration, and returns a transcript. The current adapter expects WAV; use a trusted local converter to prepare 16 kHz mono 16-bit PCM WAV from other formats. It does not download models, execute a shell, or send audio to a remote service.

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
