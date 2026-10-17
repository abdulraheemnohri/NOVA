# Offline Deployment — Debian

1. On a connected staging machine, obtain trusted Python wheels, npm packages, LiteRT-LM runtime and model files.
2. Record SHA-256 checksums and transfer artifacts using approved media.
3. Install Python from a local wheelhouse: `pip install --no-index --find-links ./wheelhouse -e '.[dev]'`.
4. Prepare the npm cache/package archive; ordinary `npm install` may require registry access.
5. Install LiteRT-LM using instructions for the exact release and architecture; validate actual supported CLI/API flags.
6. Bind its server to 127.0.0.1 and configure NOVA_LITERT_BASE_URL and NOVA_LITERT_MODEL.
7. Register a model artifact in Model Manager using its absolute path on the backend host. Confirm its SHA-256 and format before selecting it. The current registry accepts individual files, not directory bundles.\n8. Select only a model supported by the installed LiteRT-LM runtime; catalog entries for speech, vision, OCR, embeddings and other formats do not imply those runtimes are implemented.\n9. Start API with `uvicorn nova.main:app --app-dir backend --host 127.0.0.1 --port 8000`.
10. Disconnect network interfaces and rerun health, model selection, chat, policy, and audit tests.

Runtime/model binaries are not bundled by this repository. Hardware acceleration must be tested on the target machine.
