# Offline Deployment — Debian

1. On a connected staging machine, obtain trusted Python wheels, npm packages, LiteRT-LM runtime and model files.
2. Record SHA-256 checksums and transfer artifacts using approved media.
3. Install Python from a local wheelhouse: `pip install --no-index --find-links ./wheelhouse -e '.[dev]'`.
4. Prepare the npm cache/package archive; ordinary `npm install` may require registry access.
5. Install LiteRT-LM using instructions for the exact release and architecture; validate actual supported CLI/API flags.
6. Bind its server to 127.0.0.1 and configure NOVA_LITERT_BASE_URL and NOVA_LITERT_MODEL.
7. Start API with `uvicorn nova.main:app --app-dir backend --host 127.0.0.1 --port 8000`.
8. Disconnect network interfaces and rerun health, chat, policy, and audit tests.

Runtime/model binaries are not bundled by this repository. Hardware acceleration must be tested on the target machine.
