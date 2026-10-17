# NOVA Implementation Roadmap

This roadmap distinguishes implemented behavior from planned work. A screen or API stub is not considered complete without persistence, policy checks, audit events, tests, documentation, and offline behavior.

## Implemented foundation
- FastAPI API and React/TypeScript/Tailwind dashboard.
- Loopback-only LiteRT-LM OpenAI-compatible endpoint; no cloud or alternate inference fallback for chat.
- Local bearer-token authentication, default-deny tool policy, approval-gated workspace writes and snapshot rollback.
- SQLite model registry, curated catalog/device tiers, SHA-256 artifact validation, optional Hugging Face metadata/artifact import.
- Local document import/search, goals, memory, approvals, audit verification, snapshots and rollback UI.
- Persistent task queue API and UI with explicit lifecycle transitions, priority, timezone-aware due times, plan steps, result, attempts and audit records.
- Lease-based local scheduler with opt-in background worker, recovery after expired leases, bounded retry metadata, due-task priority ordering, audit events, and Scheduler UI. It only moves due tasks to Planned for human review; it never executes commands or model-generated plans.
- Read-only runtime diagnostics API/UI for LiteRT-LM endpoint status, model IDs, configured-model presence, CLI discovery, host details and audit integrity.
- Task-scoped runtime inventory for LiteRT-LM, whisper.cpp, Piper, ONNX Runtime, TFLite/LiteRT Python packages, llama.cpp and Transformers.
- Local whisper.cpp WAV transcription and Piper WAV synthesis endpoints with bounded inputs/timeouts, shell=False, temporary workspace-local files, and audit events. Piper requires a local ONNX voice and matching metadata sidecar.
- Runtime Manager UI for engine discovery, transcription, speech synthesis and local audio playback. ONNX/TFLite model execution and llama.cpp chat fallback remain disabled.

## Remaining work (not yet complete)
1. Real target-device smoke tests for whisper.cpp and Piper, plus release-specific LiteRT-LM version reporting and model/accelerator validation.
2. Semantic RAG with local embeddings, vector/hybrid retrieval and grounded citations.
3. Approval-bound task execution adapters and production OS-level sandboxing. The current scheduler only dispatches due tasks to human review; it does not execute tools.
4. Approval-bound tool execution and production OS-level sandboxing.
5. Expand audio support with streaming/realtime ASR, additional input formats, voice/model selection, and voice activity detection.
6. ONNX embeddings/OCR/classification and TFLite/LiteRT edge model execution adapters; runtime detection alone is not inference support.
7. Image/audio OCR and transcription ingestion, plus adversarial content-isolation tests. PDF/DOCX text extraction is now supported when the optional local parsers are installed.
8. Full settings validation and safe editable settings persistence.
9. Multi-user RBAC, CSRF protections for browser-session deployments, rate limiting and encrypted sensitive storage.
10. Workflow builder, multi-agent state machine, critic/verifier, prompt-injection tests, and air-gapped integration tests against supported runtimes and target hardware.

## Definition of done
A feature is complete only when API, UI controls, persistence, permission checks, audit events, tests, docs, and offline behavior exist and pass CI. Never claim GPU/NPU or model compatibility without a real target-device test.
