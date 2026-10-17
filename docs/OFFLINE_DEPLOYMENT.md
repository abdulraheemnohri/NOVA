# Offline Deployment — Debian

1. On a connected staging machine, obtain trusted Python wheels, npm packages, LiteRT-LM runtime and model files.
2. Record SHA-256 checksums and transfer artifacts using approved media.
3. Install Python from a local wheelhouse: `pip install --no-index --find-links ./wheelhouse -e '.[dev]'`.
4. Prepare the npm cache/package archive; ordinary `npm install` may require registry access.
5. Install LiteRT-LM using instructions for the exact release and architecture; validate actual supported CLI/API flags.
6. Bind its server to `127.0.0.1` and configure `NOVA_LITERT_BASE_URL` and `NOVA_LITERT_MODEL`.
7. Register a model artifact in Model Manager using its absolute path on the backend host. Confirm its SHA-256 and format before selecting it. The current registry accepts individual files, not directory bundles.
8. Optional connected setup: use the Hugging Face page to search model metadata and explicitly download supported artifacts. Set `NOVA_HUGGINGFACE_CACHE_DIR` and `NOVA_HUGGINGFACE_MAX_DOWNLOAD_BYTES` as needed. For gated/private repositories, set `NOVA_HUGGINGFACE_TOKEN` in the backend environment; never commit the token.
9. Review each model card and license, confirm provenance and checksums, then register/select only a compatible LiteRT-LM artifact. Other formats are inventory-only.
10. Start the API with `uvicorn nova.main:app --app-dir backend --host 127.0.0.1 --port 8000`.
11. Disconnect network interfaces and rerun health, model selection, chat, policy and audit tests. Hub search/download is intentionally unavailable offline, while cached model files remain on disk.

Runtime/model binaries are not bundled by this repository. Hardware acceleration must be tested on the target machine.
