# NOVA Implementation Roadmap

This roadmap distinguishes implemented behavior from planned work. A screen or API stub is not considered complete without persistence, policy checks, audit events, tests, documentation, and offline behavior.

## Implemented foundation
- FastAPI API and React/TypeScript/Tailwind dashboard.
- Loopback-only LiteRT-LM OpenAI-compatible endpoint; no cloud or alternate inference fallback.
- Local bearer-token authentication, default-deny tool policy, approval-gated workspace writes and snapshot rollback.
- SQLite model registry, curated catalog/device tiers, SHA-256 artifact validation, optional Hugging Face metadata/artifact import.
- Local document import/search, goals, memory, approvals, audit verification, snapshots and rollback UI.
- Persistent task queue API and UI: create/list/filter/delete tasks; explicit lifecycle transitions; priority, optional timezone-aware due time, plan steps, result, attempt count and audit records.
- Task queue is intentionally not a command executor. It never runs shell commands or executes model-generated plans.
- Read-only runtime diagnostics API and UI: LiteRT-LM endpoint status, model IDs exposed by the server, configured-model presence, CLI PATH discovery, Python/platform/disk details, audit-chain status and explicit compatibility limitations.

## Remaining work (not yet complete)
1. Runtime diagnostics still need release-specific version reporting and real target-device/model smoke tests; the UI deliberately does not execute arbitrary CLI binaries or infer accelerator support.
2. Expand task-scoped runtime adapters: Piper TTS generation, ONNX embeddings/OCR/classification, and TFLite/LiteRT edge inference. Current inventory detection is not equivalent to those adapters being implemented.
2. Semantic RAG with local embeddings, vector/hybrid retrieval and grounded citations.
3. Scheduler worker with leases, retries, cancellation, recovery and explicit policy-gated task execution.
4. Approval-bound tool execution and production OS-level sandboxing.
5. Voice: real ASR/TTS adapters with model/dependency checks and UI controls.
6. Vision/OCR adapters and secure file ingestion for PDF/DOCX/images/audio.
7. Full settings validation and safe editable settings persistence.
8. Multi-user RBAC, CSRF protections for browser-session deployments, rate limiting and encrypted sensitive storage.
9. Workflow builder, multi-agent state machine, critic/verifier and prompt-injection tests.
10. Air-gapped integration tests against supported LiteRT-LM releases, artifacts and target hardware.

## Definition of done
A feature is complete only when API, UI controls, persistence, permission checks, audit events, tests, docs, and offline behavior exist and pass CI. Never claim GPU/NPU or model compatibility without a real target-device test.
