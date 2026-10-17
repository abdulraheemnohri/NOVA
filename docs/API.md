# NOVA Local API Reference

Base URL: `http://127.0.0.1:8000/api`. All endpoints except `GET /health` require `Authorization: Bearer <token>`. On first startup, read the locally generated token from `data/api.token` (or `NOVA_API_TOKEN_FILE` if configured). The API never returns the token. Keep the service bound to loopback; do not expose it to a LAN or public interface.

## System monitoring\n- `GET /system`: read-only CPU/processor, RAM/swap, storage, battery, GPU, NPU and TPU telemetry. NVIDIA GPU utilization is available when `nvidia-smi` works. On Linux, AMD and Intel GPU utilization, VRAM and temperature are read from sysfs when the kernel driver exposes them. Android adds per-core CPU frequency hints, battery readings from power_supply sysfs or optional Termux:API, accessible shared-storage volumes, and best-effort Qualcomm Adreno/ARM Mali GPU counters. Android NPU/TPU presence depends on device-node visibility and cannot be guaranteed without vendor driver access. Requires the local API bearer token.\n\n## Scheduler
- `GET /scheduler/status`: report worker state, due backlog, active leases and execution contract.
- `PUT /scheduler/config`: persist the background-worker toggle and poll interval (5–3600 seconds) in local SQLite. This only changes scheduling; it does not grant tool permissions.
- `POST /scheduler/run-once`: dispatch due tasks to `planned` for operator review. No commands or tools are executed.

## Runtime
- `GET /health`: API status, LiteRT-LM endpoint reachability, and audit-chain verification.
- `GET /settings`: read-only runtime and policy summary.
- `GET /audit/verify`: verify the JSONL audit hash chain.
- `POST /chat`: send a prompt to the configured loopback LiteRT-LM-compatible endpoint. There is no cloud or alternate-runtime fallback.

## Knowledge, goals, and memory
- `POST /documents/import`: import supported local text content.
- `POST /documents/import-file` (multipart `file`): locally extract text from PDF/DOCX uploads, with a 20 MB input limit, 500-page PDF limit, bounded DOCX archive expansion and audit metadata. Requires optional `pypdf` / `python-docx`; scanned PDFs need a separate local page-rasterization step followed by the OCR endpoint.
- `POST /search`: local lexical search; semantic vector search is not implemented yet.
- `GET /goals`, `POST /goals`: list and create goal records.
- `POST /goals/{goal_id}/status`: update a goal to `open`, `in_progress`, `completed`, or `paused`; each transition is audit logged.
- `GET /memory`, `POST /memory`, `DELETE /memory/{id}`: memory CRUD.

## Approval and recovery
- `GET /approvals`: list approval records.
- `POST /approvals`: request approval for a registered action requiring approval.
- `POST /approvals/{id}/decision?decision=approve|reject`: record an approval decision.
- `POST /workspace/write`: write UTF-8 content only when an approval matches the exact relative path and SHA-256 of the content.
- `GET /workspace/snapshots`: list the latest 100 snapshot records.
- `POST /workspace/rollback`: provide a snapshot ID to restore prior bytes or remove a file created by the write. Each snapshot can be rolled back once.

For an approved write, calculate the content SHA-256, request approval for action `workspace_write` with the exact relative path and digest, approve the returned ID, then call the write endpoint with that ID and identical content. Keep the returned snapshot ID for recovery.

These are early-stage endpoints. Multi-user identity/RBAC, adversarial testing, and concurrent-write race testing remain necessary before production use. Write approvals are conditionally claimed once and marked consumed after a successful write.

## Destructive rollback approval

A workspace rollback is a high-risk action. Create an approval with action `rollback_snapshot` and payload `{"snapshot_id":"<exact snapshot id>"}`, explicitly approve it, then call `POST /api/workspace/rollback` with both `snapshot_id` and `approval_id`. The API rejects missing or mismatched approvals and consumes the approval after rollback. The UI asks for confirmation and submits this approval sequence.

## Persisted operator preferences
- `GET /settings/preferences`: read locally persisted workbench preferences.
- `PUT /settings/preferences`: validate and persist `chat_max_tokens` (64–4096), `auto_refresh_seconds` (0–300; 0 disables polling), and `confirm_model_selection` (boolean). Unknown fields are rejected.
- Preference changes are stored in the local SQLite settings table and appended to the audit chain. These preferences cannot change the inference runtime, network binding, tool allowlist, or weaken approval policy.


## Chat retrieval and source metadata
`POST /chat` performs local keyword retrieval against indexed document chunks before inference. When matches exist, bounded excerpts are included in the prompt with an explicit untrusted-data warning; the response returns a separate `sources` array containing document/chunk IDs and lexical overlap scores. Scores are not calibrated confidence values, and this is not semantic/vector RAG. The model can still make unsupported claims; inspect source excerpts before relying on an answer.


## Self-created skills and safe tool proposals
- `GET /self/skills`, `POST /self/skills`, `POST /self/skills/{id}/activate`: persist and explicitly activate user-reviewed skill instructions. Instructions are stored as data and are not interpreted as code.
- `GET /self/tools`, `POST /self/tools`, `POST /self/tools/{id}/review`: list, propose, and review tools limited to existing calculator and local knowledge-search primitives with exact fixed schemas. Review does not register new capabilities or execute generated code.
- These endpoints are under `/api`; the normal local bearer-token and audit-integrity middleware applies.
