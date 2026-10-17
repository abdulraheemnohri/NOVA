# NOVA Implementation Roadmap

This file distinguishes shipped foundation from planned work; a screen or API stub is not considered a complete feature.

## Implemented in this branch
- FastAPI app and React/TypeScript/Tailwind dashboard shell.
- Loopback-only LiteRT-LM-compatible HTTP adapter; no remote model providers or inference fallback.
- Basic health endpoint and local runtime connectivity check.
- Explicit default-deny tool registry.
- SQLite approval records and decisions.
- Workspace-contained write endpoint; approval must match the exact relative path and content SHA-256.
- Pre-write copy for existing files.
- SHA-256 hash-chained JSONL audit log and verifier.
- Initial tests, CI workflow, Debian/offline documentation.

## Remaining implementation
1. Authentication, secure session handling, RBAC, CSRF and rate limiting.
2. PDF/DOCX/image/audio ingestion, OCR, chunking, local embedding adapter and vector/hybrid retrieval with citations.
3. User-controlled episodic/semantic/procedural memory and deletion/retention controls.
4. Goals, editable plans, task scheduler, cancellation, retries and recovery.
5. Approval-bound action execution, tool registry UI and sandboxed code execution using OS isolation.
6. Transactional snapshots, restore/rollback UI, backups and restore drills.
7. Workflow builder, multi-agent state machine, critic/verifier and prompt-injection tests.
8. Voice/vision modules with dependency and model checks.
9. Full settings validation, model manager, manifest/checksum validation, benchmark suite.
10. Air-gapped integration tests against actual LiteRT-LM builds and model artifacts.

## Definition of done
A feature is complete only when its API, UI controls, persistence, permission checks, audit events, tests, documentation, and offline behavior all exist and pass CI. The actual LiteRT-LM release/model/hardware combination must be tested on target hardware; this repository cannot truthfully claim GPU/NPU support without that evidence.
