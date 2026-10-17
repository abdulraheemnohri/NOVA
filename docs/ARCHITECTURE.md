# Architecture

- React + TypeScript + Tailwind frontend.
- FastAPI/Pydantic backend and SQLite metadata.
- LiteRT-LM only, through a loopback OpenAI-compatible endpoint if supported by the installed release.
- JSONL SHA-256 chained audit log.
- Explicit tool allowlist and approval-gated writes.

Current APIs: health, chat, approvals, workspace write, audit verification, and read-only settings. Document ingestion/RAG, memory, goal planning, workflows, multimodal support, authentication, and production sandbox remain follow-on milestones.
