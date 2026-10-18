# Real-device installation and release validation

This guide is the release checklist for installing NOVA on a real Debian/Ubuntu or Android/Termux-compatible device. It distinguishes source setup from model/runtime installation: the setup script does **not** download model weights, install LiteRT-LM, or prove that a model works on a given accelerator.

## 1. Supported baseline

- Python 3.11 or newer.
- Node.js 18 or newer and npm for the React/Vite web UI.
- Debian/Ubuntu is the automated setup target. Other Linux distributions require equivalent system packages and manual setup.
- SQLite and local filesystem storage are used by default.
- Docker and cloud inference credentials are not required.
- LiteRT-LM is the only supported chat inference runtime. llama.cpp, ONNX Runtime, TFLite/LiteRT Python, Whisper.cpp and Piper are not automatic chat fallbacks.

Android/Termux support is best-effort. Android devices vary by ABI, libc availability, storage permissions, thermal policy and accelerator drivers. A successful UI launch is not proof of model-runtime compatibility.

## 2. Debian/Ubuntu setup

From a terminal:

```bash
sudo apt-get update
sudo apt-get install -y git curl ca-certificates
git clone https://github.com/abdulraheemnohri/NOVA.git
cd NOVA
git switch main
git pull --ff-only
bash scripts/setup_debian.sh
```

The setup script installs/checks Python, pip/venv, build tools, Node.js/npm, creates `.venv`, installs `requirements-dev.txt`, copies `.env.example` to `.env` if needed, installs frontend dependencies and prepares local data directories. It does not download model files.

If the distribution repository ships Node.js older than 18, install a supported Node.js 18+ release using your preferred trusted package source, then rerun setup.

## 3. Configuration and secrets

Review `.env.example` and configure only the settings needed for your installation. Keep the backend bound to loopback unless you have deliberately designed and secured a remote deployment.

Important rules:

- Never commit `.env`, `data/api.token`, private Hugging Face tokens, databases, audit logs or user documents.
- On first startup, NOVA creates `data/api.token`; read it locally and enter it into the UI sign-in page.
- Do not paste the token into issues, chat, screenshots or logs.
- Keep `NOVA_LITERT_BASE_URL` on loopback (default `http://127.0.0.1:9379/v1`) when the local inference server runs on the same device.
- Use `NOVA_HUGGINGFACE_TOKEN` only in the backend environment if a gated/private repository requires it. Public model browsing/downloads may not need a token.
- Optional speech binaries and model paths are explicit configuration. Missing optional engines should report unavailable, not trigger an automatic install or fallback.

## 4. Install and start LiteRT-LM separately

NOVA does not install or launch LiteRT-LM automatically because runtime commands, supported artifact formats and accelerator compatibility vary by LiteRT-LM release and target device.

1. Install a LiteRT-LM release compatible with your OS, CPU architecture and accelerator from its trusted upstream distribution.
2. Check that release's own documentation for the exact server command and supported model format. Do not copy a CLI command from another version without checking its help output.
3. Obtain a model explicitly documented as compatible with that runtime and device.
4. Start the runtime's OpenAI-compatible server on loopback port 9379, or set `NOVA_LITERT_BASE_URL` to the actual local loopback endpoint.
5. Confirm the endpoint responds and exposes the intended model ID before selecting it in NOVA.

A model appearing in a model list or passing a SHA-256 calculation does not establish that it is compatible, trustworthy, or able to run within device memory. Check the publisher, license, source, expected RAM/storage, context length, quantization, supported architecture and accelerator requirements.

## 5. Model Manager and downloads

Open **Model Manager** in the NOVA UI.

1. Search the curated local catalog or use the Hugging Face page to inspect repository metadata and files.
2. Read the model card, license, source and hardware requirements before downloading.
3. Select a supported artifact and explicitly start the download. Downloads require network access; cached files are local afterward.
4. Wait for the download to finish and review the locally calculated SHA-256 and registered artifact metadata.
5. Register/select only an artifact format documented as supported by the installed LiteRT-LM release. In the current implementation, only registered `.litertlm` files are eligible for chat selection; `.gguf`, `.tflite`, `.onnx` and `.safetensors` are inventory artifacts unless a compatible task adapter exists.
6. Start/verify the separate runtime, select the exact model ID reported by it, and run a short prompt.
7. Test a longer prompt only after the short test succeeds, monitoring memory, thermal behavior and latency.

The downloader restricts file types and size, writes files atomically, hashes downloaded data, and audit-logs metadata. A locally computed hash is useful for integrity tracking but proves publisher authenticity only when compared with a trusted publisher-provided digest. Never execute code from a downloaded model repository.

## 6. Start NOVA

Open two terminals in the repository.

Terminal A:

```bash
bash scripts/run_backend.sh
```

Terminal B:

```bash
bash scripts/run_frontend.sh
```

Open `http://127.0.0.1:5173` on the same device. For a phone browser connecting to a server on another device, do not simply expose the API to the LAN: configure a deliberate authenticated, encrypted deployment and firewall policy first.

## 7. Automated validation

Run the complete local gate after installation:

```bash
python scripts/doctor.py
bash scripts/check_optional_runtimes.sh
bash scripts/check.sh
```

The check script runs Python compilation, shell syntax checks, pytest, pip dependency consistency, Ruff checks for scripts, frontend tests and a production frontend build. Save the terminal output for release evidence. Fix failures; do not mark the release ready just because the UI opens.

## 8. Real-device smoke test matrix

Record device model, OS build, CPU architecture, Python/Node versions, available RAM/storage, LiteRT-LM version, model filename, model ID, quantization and accelerator.

- [ ] Backend starts with loopback binding and health endpoint responds.
- [ ] UI loads at desktop and narrow/mobile viewport widths without horizontal overflow.
- [ ] Sign-in rejects a missing/invalid token and accepts the local token.
- [ ] Diagnostics report endpoint reachability, configured model presence and audit-chain status.
- [ ] A short prompt completes through the local LiteRT-LM server.
- [ ] Disconnect network after setup; cached model listing and local chat still work if the runtime/model are already installed.
- [ ] Model download rejects disallowed extensions and over-limit files; interrupted/failed downloads do not leave a falsely registered complete artifact.
- [ ] Local document import/search returns source metadata; verify a citation quote against the exact imported source.
- [ ] Task creation and status transitions persist across backend restart.
- [ ] Workflow run, failure path, cancellation, checkpoint history and audit records behave as documented.
- [ ] Unapproved writes remain blocked; unknown tools are denied.
- [ ] Audit verification passes before and after representative operations.
- [ ] Optional Whisper/Piper tests are performed only when the actual binaries, model assets and supported sample files are installed.
- [ ] Run repeated prompts while monitoring memory, temperature, battery and latency; stop if the device becomes unstable or overheats.

Record each item as PASS, FAIL, BLOCKED or NOT APPLICABLE, with logs and a short note. Never record GPU/NPU acceleration as working unless a real inference test confirms it.

## 9. Offline / air-gapped installation

A source archive is not a complete offline installer. Before disconnecting, stage for the target architecture:

- Python wheels for all required dependencies and a compatible pip cache.
- Frontend npm dependencies / package cache and lockfile.
- Compatible LiteRT-LM runtime binaries and model artifact.
- Any optional Whisper/Piper executables and their local model/voice assets.
- Checksums, licenses, model cards and installation notes.

Transfer only reviewed artifacts. Do not include `.env`, API tokens, personal databases, audit logs or workspace documents in a distributable bundle. Run the full check suite and offline smoke tests after transfer.

## 10. Known release limitations

This is a local-first engineering release, not a claim of production-grade multi-user deployment. Current limits include single-operator bearer-token authentication, no production OS-level sandbox for arbitrary tools, no full RBAC/CSRF model for multi-user browser deployment, and no automatic chat fallback to other runtimes. Semantic retrieval benchmark metrics measure retrieval ranking, not factual entailment. Hardware compatibility must be demonstrated on the exact target device.

For detailed architecture, security and optional runtime configuration, see `docs/ARCHITECTURE.md`, `docs/SECURITY.md`, `docs/MODEL_RUNTIMES.md`, `docs/OFFLINE_DEPLOYMENT.md` and `docs/ROADMAP.md`.
