# NOVA Implementation Roadmap

This roadmap distinguishes implemented behavior from planned work. A screen or API stub is not considered complete without persistence, policy checks, audit events, tests, documentation, and offline behavior.

## Implemented foundation
- FastAPI API and React/TypeScript/Tailwind dashboard.
- Loopback-only LiteRT-LM OpenAI-compatible endpoint; no cloud or alternate inference fallback for chat.
- Local bearer-token authentication, default-deny tool policy, approval-gated workspace writes and snapshot rollback.
- SQLite model registry, curated catalog/device tiers, SHA-256 artifact validation, optional Hugging Face metadata/artifact import.
- Local document import/search, goals, memory, approvals, audit verification, snapshots and rollback UI.
- Chat-time local lexical retrieval with bounded reference excerpts, source/chunk metadata returned separately, UI source disclosure, and prompt text marking document content as untrusted.
- Optional CPU-only semantic/hybrid retrieval using a user-supplied local SentenceTransformers model directory, with persistent SQLite embedding cache invalidated by model-file fingerprints; lexical-only behavior remains the default and fallback.
- Persistent task queue API and UI with explicit lifecycle transitions, priority, timezone-aware due times, plan steps, result, attempts and audit records.
- Lease-based local scheduler with opt-in background worker, recovery after expired leases, bounded retry metadata, due-task priority ordering, audit events, and Scheduler UI. It only moves due tasks to Planned for human review; it never executes commands or model-generated plans.
- Read-only runtime diagnostics API/UI for LiteRT-LM endpoint status, model IDs, configured-model presence, CLI discovery, host details and audit integrity.
- Persisted operator preferences API/UI for chat token limits, opt-in automatic status polling, and model-switch confirmation; values are range-validated, stored in SQLite, and audit logged.
- System Monitor API/UI for CPU/processor utilization, RAM/swap, storage, battery, NVIDIA GPU telemetry through nvidia-smi, best-effort AMD/Intel GPU utilization/VRAM/temperature from Linux sysfs, Android per-core frequency/battery/storage/Qualcomm Adreno and ARM Mali GPU hints, and best-effort NPU/TPU device detection.
- Task-scoped runtime inventory for LiteRT-LM, whisper.cpp, Piper, ONNX Runtime, TFLite/LiteRT Python packages, llama.cpp and Transformers.
- Local whisper.cpp WAV transcription and Piper WAV synthesis endpoints with bounded inputs/timeouts, shell=False, temporary workspace-local files, and audit events. Piper requires a local ONNX voice and matching metadata sidecar.
- Runtime Manager UI for engine discovery, transcription, speech synthesis and local audio playback. ONNX/TFLite model execution and llama.cpp chat fallback remain disabled.

- Startup recovery marks abandoned autonomous runs as `interrupted`, preserves the last checkpoint and audit trail, and deliberately does not replay side effects automatically. Interrupted runs can request a fresh validated plan for operator review without executing tools.
- Autonomous planner now preflights every proposed step and exact tool input schema before any execution; invalid arithmetic, unexpected fields, unsupported tools, overlong inputs, and malformed reasons reject the whole plan before partial execution. Operators can request cancellation of a running workflow; cancellation is persisted and observed between tool steps, with a terminal cancelled state and audit event.\n\n## Newly implemented self-improvement foundation
- Persisted self-created skills with bounded Markdown instructions, tags, draft-by-default lifecycle, explicit activation, versioning, and audit events.
- Self-created tool proposals are declarative only: proposals must map exactly to existing bounded calculator or local knowledge-search primitives and their fixed input schemas. Proposals require a separate review transition; generated code is never executed and model output cannot register a new runtime capability.
- API endpoints are under `/api/self/skills` and `/api/self/tools`; user-interface management and controlled skill execution remain follow-up work.

## Newly implemented hardening
- Process-local API request rate limiting and a separate failed-authentication budget, with basic response security headers. This is single-process defense in depth, not multi-user RBAC or an edge limiter.

## Remaining work (not yet complete)
1. Real target-device smoke tests for whisper.cpp and Piper, plus release-specific LiteRT-LM version reporting and model/accelerator validation.
2. Retrieval evaluation, citation-level grounding verification, and large-corpus performance work for semantic RAG.
3. Approval-bound task execution adapters and production OS-level sandboxing. Task lifecycle now supports a configurable 1–10 attempt budget and concurrency-safe status transitions; the current scheduler only dispatches due tasks to human review and does not execute tools.
4. Approval-bound tool execution and production OS-level sandboxing.
5. Expand audio support with streaming/realtime ASR, additional input formats, voice/model selection, and voice activity detection.
6. ONNX embeddings/OCR/classification and TFLite/LiteRT edge model execution adapters; runtime detection alone is not inference support.
7. Streaming audio and adversarial content-isolation tests. Scanned-PDF OCR is now opt-in and requires Poppler + Tesseract. PDF/DOCX text extraction, explicit Tesseract image OCR, and opt-in scanned-PDF OCR are supported when their optional local dependencies are installed.
8. Broader operational settings validation and safe editable settings persistence; the bounded workbench preference subset is implemented.
9. Multi-user RBAC, CSRF protections for browser-session deployments, persistent/distributed rate-limit storage and encrypted sensitive storage.
10. Workflow builder, multi-agent state machine, critic/verifier, prompt-injection tests, and air-gapped integration tests against supported runtimes and target hardware.

## Definition of done
A feature is complete only when API, UI controls, persistence, permission checks, audit events, tests, docs, and offline behavior exist and pass CI. Never claim GPU/NPU or model compatibility without a real target-device test.

- [x] Opt-in GitHub updater with trusted repository checks, validation, rollback on test failure, scheduled checks/install settings, and explicit Linux/systemd reboot control. A process restart is still required when reboot is disabled.
- [x] WhatsApp Cloud API bridge with signed webhooks, sender allowlisting, up to five external agent endpoints, and explicit non-E2E-encryption disclosure. Meta account setup and public webhook deployment remain operator tasks.
