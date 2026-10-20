# NOVA mobile Debian runtime orchestration

## Goal

Gemma 4 E4B through LiteRT-LM is the primary chat/reasoning model. Optional local runtimes are task workers, not alternate chat providers. NOVA must not silently switch the primary model when a runtime is missing.

Google describes Gemma 4 E2B/E4B as mobile/edge models with audio and visual understanding and native function calling. Actual support depends on the exact model artifact, LiteRT-LM build, API request format, and hardware. NOVA must probe capabilities rather than infer them from the model name. See https://deepmind.google/models/gemma/gemma-4/ and https://ai.google.dev/gemma/docs.

## Runtime policy

- **LiteRT-LM / Gemma 4 E4B:** primary model. Keep its server under the existing explicit operator-managed configuration; do not let model output directly execute shell commands.
- **whisper.cpp:** optional audio transcription adapter. Start its CLI only for an explicit transcription job; terminate when the command completes or reaches its timeout.
- **Piper:** optional local text-to-speech adapter. Start only for synthesis jobs; a compatible voice .onnx and sidecar .onnx.json are required.
- **FFmpeg:** optional audio preprocessing for supported non-WAV uploads; invoked only inside a bounded task.
- **Tesseract + Pillow:** optional OCR path when the operator uses NOVA's OCR endpoint. This is not proof that Gemma's own vision capability is unavailable.
- **ONNX Runtime / TFLite / Transformers / llama.cpp:** optional libraries/tools are listed by the existing runtime inventory. They are not automatically made the primary chat model and are not all guaranteed to be compatible with a Gemma 4 artifact. Install only when a concrete feature needs them.

## Start/stop contract

The task lifecycle wrapper accepts only fixed runtime IDs and executable basenames, prohibits shell mode, requires a timeout up to 600 seconds, records a bounded in-memory lifecycle history, and applies a concurrency limit. Profiles:
- mobile: one managed task at a time.
- balanced: two managed tasks.
- performance: three managed tasks.

Managed child commands exit at completion; NOVA does not kill unrelated processes. A timeout is enforced by Python's subprocess timeout. The lifecycle status is an activity snapshot, not a promise that every external service or model is loaded.

Endpoint: authenticated GET /api/runtimes/lifecycle. Existing GET /api/runtimes reports installation/configuration state. The lifecycle manager only controls task-scoped subprocesses that use its wrapper; it does not yet own the separately configured LiteRT-LM server process.

## Mobile Debian install

Run from the repository root inside Debian (for example, a Debian proot on Android). The script installs system packages and NOVA dependencies, creates/uses .venv, installs frontend packages, and sets NOVA_RUNTIME_PROFILE=mobile. It does not download model weights or voice files.

Core dependencies:
```bash
bash scripts/install_mobile_debian.sh
```

Install LiteRT-LM CLI, whisper.cpp, Piper and ONNX Runtime packages:
```bash
bash scripts/install_mobile_debian.sh --all-runtimes
```

Install only selected components:
```bash
bash scripts/install_mobile_debian.sh --with-litert-lm
bash scripts/install_mobile_debian.sh --with-whisper-cpp
bash scripts/install_mobile_debian.sh --with-piper
bash scripts/install_mobile_debian.sh --with-onnx
```

Review free disk before building whisper.cpp or downloading any model. These options install tools/libraries only. Configure exact CLI paths in NOVA's local .env, choose model/voice files explicitly, and check python scripts/doctor.py before use.

## Upgrade and verify

```bash
git fetch origin --prune
git switch main
git pull --ff-only origin main
bash scripts/install_mobile_debian.sh
bash scripts/check.sh
python scripts/doctor.py
```

Start backend and frontend in separate terminals using the repository's documented launch scripts. Confirm the API token is configured and use authenticated requests for runtime endpoints.

## Known limits / safety

- This repository change adds lifecycle management to task-scoped CLI runtimes; it does not prove actual inference or multimedia capability on a specific phone.
- LiteRT-LM service lifecycle remains separately configured. Do not stop it automatically until chat requests are tracked and the service ownership/idle policy is implemented and tested.
- Native Gemma 4 audio/vision should be used when the selected LiteRT-LM model artifact and endpoint actually support it. Otherwise, only an explicit task adapter may be selected; never invent capabilities or silently route private data to a cloud API.
- Android Termux is not identical to Debian proot. Native packages, CPU instructions, Python wheels, systemd, and build toolchains may differ. The installer requires apt-get and checks Python/Node versions.
- Do not run model-generated shell strings. Tool calls must be schema-validated, allowlisted, policy-checked, and approval-gated.
- Avoid keeping multiple multi-billion-parameter models loaded simultaneously on a phone. A task CLI exiting does not necessarily release memory held by an independently running model server.