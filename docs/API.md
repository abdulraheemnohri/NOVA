# NOVA Local API Reference

Base URL: `http://127.0.0.1:8000/api`. The API has no authentication yet. Keep it bound to loopback; do not expose it to a LAN or public interface.

## Runtime
- `GET /health`: API status, LiteRT-LM endpoint reachability, and audit-chain verification.
- `GET /settings`: read-only runtime and policy summary.
- `GET /audit/verify`: verify the JSONL audit hash chain.
- `POST /chat`: send a prompt to the configured loopback LiteRT-LM-compatible endpoint. There is no cloud or alternate-runtime fallback.

## Knowledge, goals, and memory
- `POST /documents/import`: import supported local text content.
- `POST /search`: local lexical search; semantic vector search is not implemented yet.
- `GET /goals`, `POST /goals`: list and create goal records.
- `GET /memory`, `POST /memory`, `DELETE /memory/{id}`: memory CRUD.

## Approval and recovery
- `GET /approvals`: list approval records.
- `POST /approvals`: request approval for a registered action requiring approval.
- `POST /approvals/{id}/decision?decision=approve|reject`: record an approval decision.
- `POST /workspace/write`: write UTF-8 content only when an approval matches the exact relative path and SHA-256 of the content.
- `GET /workspace/snapshots`: list the latest 100 snapshot records.
- `POST /workspace/rollback`: provide a snapshot ID to restore prior bytes or remove a file created by the write. Each snapshot can be rolled back once.

For an approved write, calculate the content SHA-256, request approval for action `workspace_write` with the exact relative path and digest, approve the returned ID, then call the write endpoint with that ID and identical content. Keep the returned snapshot ID for recovery.

These are early-stage endpoints. Authentication, adversarial testing, and concurrent-write race testing remain necessary before production use. Write approvals are conditionally claimed once and marked consumed after a successful write.