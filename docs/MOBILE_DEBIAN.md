# Mobile Debian installation and on-demand runtime control

This guide targets NOVA inside a Debian/Ubuntu Linux environment on an Android phone (for example, a Debian proot). It does not install an Android APK. A Debian environment must provide `apt-get`; native Termux is not the same environment.

## 1. Install the repository

From the NOVA repository root:

```bash
bash scripts/install_mobile_debian.sh
bash scripts/check.sh
python scripts/doctor.py
```

The mobile installer installs core Python/backend and Web UI dependencies, Node.js/npm, FFmpeg, Tesseract and Pillow. It sets `NOVA_RUNTIME_PROFILE=mobile`, which limits NOVA-managed task runtimes to one at a time. It does not install every large optional Python package, download model weights, fetch voice files, or start the LiteRT-LM server.

Review available space first:

```bash
df -h .
free -h 2>/dev/null || true
python3 --version
node --version
```

## 2. Optional runtime installation

Install only the capabilities you intend to use. These commands build/install software but do not download task models or Piper voices:

```bash
# Main local chat runtime
bash scripts/install_mobile_debian.sh --with-litert-lm

# Offline speech-to-text; source compilation can take time and disk space
bash scripts/install_mobile_debian.sh --with-whisper-cpp

# Local speech synthesis
bash scripts/install_mobile_debian.sh --with-piper

# ONNX task runtime; not a chat fallback
bash scripts/install_mobile_debian.sh --with-onnx

# All supported optional runtime packages/tools
bash scripts/install_mobile_debian.sh --all-runtimes
```

`--all-runtimes` can take a long time and may use substantial storage during the Whisper C++ build. The build uses one parallel job on mobile. If storage or memory is low, install LiteRT-LM first and add one optional runtime at a time. If the Debian Python version or CPU architecture lacks a compatible upstream wheel, the installer may fail; do not force-install incompatible wheels.

## 3. Configure the local LiteRT-LM server

LiteRT-LM is NOVA's only chat/reasoning runtime. Install it with:

```bash
bash scripts/install_mobile_debian.sh --with-litert-lm
.venv/bin/litert-lm --help
.venv/bin/litert-lm serve --help
```

Use the installed version's help and the official [OpenAI-compatible server guide](https://developers.google.com/edge/litert-lm/cli/openai_server) to verify supported flags. The current documented server form is:

```bash
.venv/bin/litert-lm serve --host 127.0.0.1 --port 9379
```

Run the server in its own terminal while NOVA chat is in use. Keep it on loopback; do not bind it to `0.0.0.0` on a phone. Import/download only a model supported by the installed LiteRT-LM release, and check its size and memory requirements before downloading. A Gemma 4 E4B artifact can be too demanding for a phone with around 6 GiB RAM; prefer a smaller supported quantized model if the target device cannot load E4B reliably. Do not assume that the WhatsApp default model ID is a locally installed model ID.

For NOVA's optional user-service launcher, set the exact operator-approved command in `.env`:

```dotenv
NOVA_LITERT_BASE_URL=http://127.0.0.1:9379/v1
NOVA_LITERT_LM_COMMAND=.venv/bin/litert-lm serve --host 127.0.0.1 --port 9379
NOVA_RUNTIME_PROFILE=mobile
```

The launcher resolves the command from the NOVA project root. After changing `.env`, restart the backend. On Android proot environments without systemd, run LiteRT-LM manually in a separate terminal; the systemd autostart control is not supported there.

## 4. Configure optional task runtimes

Use absolute paths in the backend `.env` when automatic executable discovery cannot find the binary. The mobile installer builds Whisper under `tools/whisper.cpp`.

```dotenv
NOVA_WHISPER_CLI_PATH=./tools/whisper.cpp/build/bin/whisper-cli
NOVA_WHISPER_MODEL_PATH=./data/models/whisper/ggml-base.bin
NOVA_FFMPEG_CLI_PATH=/usr/bin/ffmpeg
NOVA_TESSERACT_CLI_PATH=/usr/bin/tesseract
NOVA_PIPER_CLI_PATH=./.venv/bin/piper
NOVA_PIPER_MODEL_PATH=./data/models/piper/voice.onnx
NOVA_RUNTIME_PROFILE=mobile
```

The paths above are examples. Create the model directories and supply model/voice files that match the installed runtime:

```bash
mkdir -p data/models/whisper data/models/piper
```

Whisper needs a compatible GGML `.bin` model; Piper needs a compatible `.onnx` voice and matching `.onnx.json` sidecar. NOVA does not download these assets automatically. Check each asset's licensing and available RAM before use.

## 5. How the runtime controller behaves

- **Gemma 4 / LiteRT-LM:** primary chat runtime. Keep its server running while you use NOVA chat. NOVA never switches chat to Whisper, Piper, ONNX, Transformers or llama.cpp.
- **Whisper.cpp:** launched only when a transcription task is requested; stopped when the process exits or reaches its bounded timeout.
- **FFmpeg:** launched only when a supported non-WAV audio upload needs local normalization; stopped when conversion completes.
- **Piper:** launched only for a synthesis request; stopped after producing the audio response or timing out.
- **Tesseract:** launched only for an OCR request; stopped when OCR completes.
- **ONNX Runtime/Pillow:** Python libraries, not always-on daemons. They do not execute arbitrary models merely because they are installed.

The runtime lifecycle manager accepts only registered executable/runtime pairs, refuses shell execution, bounds process timeouts, and limits simultaneous managed jobs according to the profile: mobile=1, balanced=2, performance=3. It records bounded in-memory lifecycle metadata, not prompts, command arguments or file contents. It does not kill unrelated processes. Task-scoped commands do not remain running in the background, so no idle timer is needed for them.

The AI may request a registered task capability through NOVA's existing task/UI/API flow; it cannot pass an arbitrary shell command or choose an arbitrary executable. Any future background daemon integration must add a separate reviewed adapter with explicit allowlisted start/stop behavior.

Inspect lifecycle status through the authenticated API:

```bash
bash scripts/nova-api.sh GET /api/runtimes/lifecycle
bash scripts/nova-api.sh GET /api/runtimes
bash scripts/nova-api.sh GET /api/runtimes/preflight
```

## 6. Run and verify

Terminal 1:

```bash
bash scripts/run_litert_lm.sh
```

If the exact local LiteRT-LM command is configured, this runs it in the foreground. Otherwise follow the CLI command verified in section 3.

Terminal 2:

```bash
bash scripts/run_backend.sh
```

Terminal 3:

```bash
bash scripts/run_frontend.sh
```

Open <http://127.0.0.1:5173>, sign in using the local token in `data/api.token`, and verify the Runtimes page. Then run `bash scripts/check.sh` and `python scripts/doctor.py`. Test one task at a time on the phone and monitor available RAM and thermal throttling.

## 7. Stop services and recover

Use Ctrl+C for foreground commands. For a systemd user service on a normal Debian system (not usually available in Android proot):

```bash
systemctl --user stop nova-litert-lm.service
bash scripts/install_autostart.sh status
```

To return to the low-memory profile, set `NOVA_RUNTIME_PROFILE=mobile` in `.env` and restart NOVA. If a runtime times out, inspect its configured executable/model paths and retry with a smaller model; NOVA does not automatically switch inference engines or uninstall packages as rollback.

## Upgrading later

```bash
git status --short --branch
git fetch origin --prune
git switch main
git pull --ff-only origin main
bash scripts/install_mobile_debian.sh
bash scripts/check.sh
python scripts/doctor.py
```

The upgrade script refreshes project dependencies and keeps local model files and the existing `.env`. Re-run an optional runtime installation flag only when you need that runtime or when its documented upstream version changes.
