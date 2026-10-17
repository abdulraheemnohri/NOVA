# NOVA Local API Reference

Base URL: `http://127.0.0.1:8000/api`. All endpoints except `GET /health` require `Authorization: Bearer <token>`. On first startup, read the locally generated token from `data/api.token` (or `NOVA_API_TOKEN_FILE` if configured). The API never returns the token. Keep the service bound to loopback; do not expose it to a LAN or public interface.

## Scheduler
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