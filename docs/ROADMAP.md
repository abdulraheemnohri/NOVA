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
- API endpoints are under `/api/self/skills` and `/api/self/tools`; the Self-Improvement Lab UI supports creation and review. Skill execution accepts explicit structured steps only, preflights every step, limits runs to five calls to existing calculator/local knowledge-search primitives, persists run history, and emits audit events. Natural-language instructions are not interpreted as executable plans.

## Newly implemented hardening
- On startup, approvals left in `consuming` after an interrupted write/rollback are moved to `interrupted`, audit-logged, and excluded from automatic replay; operators must inspect the workspace and retained snapshots because a crash may occur before or after the filesystem side effect.
- SQLite-backed API request rate limiting and a separate failed-authentication budget persist across restarts and are shared by workers using the same database; basic response security headers remain enabled. This is defense in depth, not multi-user RBAC or an edge limiter.

## Recently added bounded tool capability
- Added a read-only `text_stats` primitive to the agent tool catalog and skill workflow engine. It reports character, word and line counts for up to 10,000 characters; it does not execute generated code, access the network, or write files. UI workflow builder exposes it as an explicit step.

## Recently added operator usability
- About page command guide for installation, launch, diagnostics, tests, API helper and startup service commands; links to the command and API references.
- Opt-in Linux systemd per-user startup installer for backend and frontend, with status/uninstall and an explicit flag for user lingering. It does not run privileged commands or open public ports.
- Runtime API discovery documented through the live OpenAPI schema; environment/security configuration remains outside browser-editable preferences.

## Recently added safe utilities
- Added bounded JSON formatting/validation and UTF-8 Base64 encode/decode to the default-deny local tool registry.
- Agent Workbench loads the backend tool catalog and provides a JSON-input runner with visible schemas and results.
- Utility calls enforce input limits and are audit-logged; this does not enable shell, arbitrary network access, or file writes.

## Remaining work (not yet complete)
1. Real target-device smoke tests for LiteRT-LM inference, Whisper.cpp and Piper; release-specific runtime version reporting and model/accelerator validation. Follow `docs/REAL_DEVICE_TESTING.md` and record results rather than assuming hardware support.
2. Citation source/quote verification API and local retrieval benchmark evaluation are implemented. The benchmark reports Recall@k and MRR against operator-labeled chunk IDs; semantic claim-entailment checks and large-corpus performance work remain.
3. Approval-bound task execution adapters and production OS-level sandboxing. Task lifecycle now supports a configurable 1–10 attempt budget and concurrency-safe status transitions; the current scheduler only dispatches due tasks to human review and does not execute tools.
4. Approval-bound tool execution and production OS-level sandboxing.
5. Expand audio support with streaming/realtime ASR, additional input formats, voice/model selection, and voice activity detection.
6. ONNX embeddings/OCR/classification and TFLite/LiteRT edge model execution adapters; runtime detection alone is not inference support.
7. Streaming audio and adversarial content-isolation tests. Scanned-PDF OCR is now opt-in and requires Poppler + Tesseract. PDF/DOCX text extraction, explicit Tesseract image OCR, and opt-in scanned-PDF OCR are supported when their optional local dependencies are installed.
8. Broader operational settings validation and safe editable settings persistence; the bounded workbench preference subset is implemented.
9. Multi-user RBAC, CSRF protections for browser-session deployments, distributed/edge rate-limit enforcement and encrypted sensitive storage.
10. Multi-agent state machine, critic/verifier, adversarial prompt-injection tests, and air-gapped integration tests against supported runtimes and target hardware. The bounded local workflow builder, conditional execution, checkpoints, run history, and cancellation controls are implemented. Skill execution currently has a deliberately small allowlist and does not execute arbitrary generated code.

## Release validation entry point\n- [x] Added `docs/REAL_DEVICE_TESTING.md` with Debian/Ubuntu setup, secrets/configuration guidance, LiteRT-LM setup boundaries, model download workflow, offline staging and a real-device smoke-test matrix. The checklist is documentation, not evidence that target hardware tests have already passed.\n\n## Definition of done
A feature is complete only when API, UI controls, persistence, permission checks, audit events, tests, docs, and offline behavior exist and pass CI. Never claim GPU/NPU or model compatibility without a real target-device test.

- [x] Opt-in GitHub updater with trusted repository checks, validation, rollback on test failure, scheduled checks/install settings, and explicit Linux/systemd reboot control. A process restart is still required when reboot is disabled.
- [x] WhatsApp Cloud API bridge with signed webhooks, sender allowlisting, up to five external agent endpoints, and explicit non-E2E-encryption disclosure. Meta account setup and public webhook deployment remain operator tasks.


## Skill usability improvement
- Agent Workbench offers four built-in starter skill templates: structured summarizer, read-only code reviewer, project planner, and local knowledge assistant. Template-created skills start disabled and require an explicit operator enable action; skill text remains untrusted guidance and cannot grant permissions.
