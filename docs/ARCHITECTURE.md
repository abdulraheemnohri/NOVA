# Architecture

- React + TypeScript + Tailwind frontend.
- FastAPI/Pydantic backend and SQLite metadata.
- LiteRT-LM only for chat inference, through a loopback OpenAI-compatible endpoint if supported by the installed release.
- JSONL SHA-256 chained audit log and bearer-token protected local API.
- Explicit tool allowlist and approval-gated writes.
- Local model registry, hardware profiles and optional Hugging Face Hub discovery/download.
- Read-only diagnostics endpoint (`GET /api/diagnostics`) and dashboard page for endpoint/model visibility, host information, audit integrity and explicit compatibility limits.

## Model management

- `GET /api/models/catalog`, `GET /api/models`, `POST /api/models/register`, and `POST /api/models/select`.
- Hugging Face endpoints: `GET /api/models/huggingface/status`, `GET /api/models/huggingface/search?q=...`, `GET /api/models/huggingface/files?repo_id=...`, and `POST /api/models/huggingface/download`.
- The Hub integration searches metadata, lists repository files, downloads only explicit selected artifacts from an extension allowlist, enforces a configured size limit, writes atomically, computes SHA-256, caches locally, and audit-logs download/cache actions.
- Optional `NOVA_HUGGINGFACE_TOKEN` is read from the backend environment for gated/private repositories. It is never returned to the frontend.
- Hugging Face is a model-file source, not an inference provider. Only registered `.litertlm` files can be selected for chat. GGUF, ONNX, TFLite and Safetensors remain inventory-only until dedicated adapters are implemented.
- The catalog covers representative chat/reasoning/tool-calling, voice, vision, embeddings, reranking, translation, OCR and classification families, plus low-end/mid-range/high-end device profiles. Voice inference is not implemented yet.

## Current limitations

Runtime commands, endpoint compatibility, model IDs and hardware acceleration must be verified against the installed LiteRT-LM release. Hub downloads require internet and model/license review; no downloaded model code is executed. Directory bundles are not supported by the local registration API. Full sandboxing and multi-user RBAC remain follow-on milestones.
