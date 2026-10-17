# Architecture

- React + TypeScript + Tailwind frontend.
- FastAPI/Pydantic backend and SQLite metadata.
- LiteRT-LM only, through a loopback OpenAI-compatible endpoint if supported by the installed release.
- JSONL SHA-256 chained audit log.
- Explicit tool allowlist and approval-gated writes.

Model management APIs: `GET /api/models/catalog`, `GET /api/models`, `POST /api/models/register`, and `POST /api/models/select`. The catalog covers representative chat/reasoning/tool-calling, voice, vision, embeddings, reranking, translation, OCR and classification families, plus low-end/mid-range/high-end device profiles. Registration verifies a local artifact's SHA-256 but does not execute or download it. Only `litertlm` artifacts can be selected for chat; other formats are inventory-only until dedicated adapters exist. Voice inference is not implemented yet.\n\nOther APIs include health, chat, approvals, workspace write, audit verification, and settings. Full sandboxing and multi-user RBAC remain follow-on milestones.
