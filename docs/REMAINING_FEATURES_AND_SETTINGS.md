# NOVA Remaining Features, Functions, Settings and Acceptance Matrix

**Purpose:** one implementation-oriented inventory for remaining NOVA work. This is a status and acceptance contract, not a claim that every item below is already implemented or production validated.

## 1. Current architecture and product boundaries

- **Frontend:** React/Vite web UI with dashboard, chat, workbench, workflow and self-improvement pages, integrations, model management, knowledge/documents, tasks/goals/scheduler, monitoring, diagnostics, runtimes, memory, approvals, audit/safety, updates, settings and about/help.
- **Backend:** FastAPI, SQLite persistence, local workspace, bearer-token-protected routes, default-deny tool policy, approval records, audit trail, LiteRT-LM chat adapter, model and document management, task/workflow/scheduler modules, MCP stdio/Streamable HTTP and bounded API-provider execution.
- **Inference boundary:** LiteRT-LM is the supported chat path. Other model formats may be listed or downloaded but are not automatically chat runtimes. No silent cloud inference fallback.
- **Privacy boundary:** Private Chat must remain offline-only at the backend dispatch boundary. Any new network-capable tool must be classified and blocked in Private Chat.
- **Execution boundary:** tasks scheduled for review are not equivalent to unrestricted autonomous shell execution. Generated skills, plans, downloaded files and internet research remain untrusted until validated.

## 2. Feature and function matrix

| Area | Existing scope | Remaining work / acceptance criteria |
|---|---|---|
| Dashboard and navigation | Health, runtime/model status, approvals, audit and quick actions | Test every route target, loading/error/empty states, narrow/mobile layout and keyboard navigation |
| Chat and history | Local conversations, search, archive/restore, export/delete, attachments and supported browser speech | Test import/export round trips, attachment limits, cancellation, long-running model timeout and private-mode network blocking |
| Model Manager | Registry, active/inactive state, selection, preflight and device profile | Test corrupt/missing models, unsupported formats, duplicate IDs, low-disk conditions and switching while inference is active |
| LiteRT-LM | Local endpoint adapter and bounded response wait | Validate the actual CLI/server and model on each supported host; report incompatibility without cloud fallback |
| Tool policy | Default-deny policy, approvals and workspace operations | Add a policy test for every new tool; bind approval to exact operation and arguments; reject stale/replayed approvals |
| Self-Improvement Lab | Proposals, skills and tool-proposal workflows | Add provenance, isolated tests, review/enable/disable, rollback and audit events; never auto-grant permissions |
| Workflows and recovery | Workflow state and recovery records | Test crash/restart recovery, idempotent steps, cancellation, retry caps and partial failure reporting |
| Tasks and scheduler | Local task queue; due tasks staged for operator review | Add explicit task state transition tests, duplicate-run prevention, missed-run policy and disable/pause controls; do not imply arbitrary plan execution |
| MCP integrations | stdio and Streamable HTTP, tool discovery/calls, confirmation for side effects | Improve process isolation, real-server compatibility tests, timeouts/cancellation, shutdown cleanup and credential-redaction tests; SSE-only/OAuth refresh remain unsupported |
| MCP stdio sandbox setting | Optional Linux bubblewrap read-only-root/write-containment launch mode | Test on a real Linux host with user namespaces; this is not a complete sandbox and does not isolate network or hide readable host files |
| API providers | Exact path allowlists, bounded JSON GET/POST, timeout and response caps | Add provider-specific adapters only with contract tests; `header_env` and `oauth_external` are not fully implemented authentication flows |
| Knowledge base | Local indexing and lexical retrieval with source metadata | Improve document-type extraction coverage, deduplication, re-indexing, deletion propagation and citations; semantic retrieval remains opt-in |
| Hugging Face | Metadata search, file listing, bounded downloads and local token/cache status | Test interrupted downloads, checksum/integrity validation where available, disk-space checks and gated repository errors; never execute downloaded code automatically |
| Memory | Local memory CRUD/categories | Add retention policy, export, deletion verification, source/provenance, sensitive-data handling and explicit separation between user memory and generated skill content |
| Approvals | Pending/approved/rejected action queue | Ensure action digest, expiration, requester/source, replay prevention and complete audit history |
| Audit and recovery | Hash-linked records, snapshots and workspace rollback | Test tampering detection, concurrent append, partial-write recovery and restore verification; hash chaining is not immutable against a privileged administrator |
| System Monitor | Host/resource telemetry and best-effort platform metrics | Represent unsupported metrics as unavailable; add Windows/Linux/Termux host acceptance tests |
| Speech/OCR | Optional local Whisper/Piper/Tesseract/PDF OCR paths | Test missing binary/model, malicious/oversized input, timeout, language support and cleanup; features stay off when dependencies are absent |
| WhatsApp Agent Platform | Opt-in text bridge using configured local inference | Test authentication, webhook/polling errors, rate limits, message privacy warning, duplicate delivery and disconnect behavior; no media support unless implemented and tested |
| Updates and packaging | Update review and installer workflows | Verify backup-before-update, integrity checks, failure recovery, rollback and package exclusion of secrets/databases/model weights |
| Settings | UI preferences plus environment-backed runtime/security settings | Every setting must show effective value, source, restart requirement and validation; never expose secrets or let a browser weaken security policy |
| Multi-user/RBAC | Not implemented as per-user isolation; current posture is a single local operator token | Requires a separate identity, authorization, data isolation and migration design before remote multi-user use |
| Deployment | Local-first setup and operations documentation | Validate clean installs on supported Windows/Linux/macOS environments and avoid public exposure without a separately reviewed deployment profile |

## 3. Environment settings inventory

All environment variables use the `NOVA_` prefix. Keep secrets in the local environment or owner-only secret files; never commit real values.

| Setting | Purpose | Default / safety expectation |
|---|---|---|
| `NOVA_ENV` | Environment mode | `development`; set deliberately for deployment |
| `NOVA_WORKSPACE` | File-operation workspace | `./data/workspace`; use a dedicated, limited directory |
| `NOVA_DATABASE_PATH` | SQLite database | `./data/nova.sqlite3`; protect file permissions and back up before upgrades |
| `NOVA_AUDIT_PATH` | Audit log path | `./data/audit.jsonl`; writable only by the service account |
| `NOVA_LITERT_BASE_URL` | Local LiteRT-LM endpoint | `http://127.0.0.1:9379/v1`; keep loopback unless separately secured |
| `NOVA_LITERT_MODEL` | Configured model identifier | `local-model`; must match the model advertised by the local endpoint |
| `NOVA_LITERT_CHAT_TIMEOUT_SECONDS` | Chat request timeout | `120`, bounded 5–600 seconds |
| `NOVA_RUNTIME_PROFILE` | Runtime concurrency profile | `balanced`; choose based on actual device resources |
| `NOVA_REQUIRE_APPROVAL_FOR_WRITES` | Gate write actions | `true`; do not disable casually |
| `NOVA_SCHEDULER_ENABLED` | Background due-task staging | `false`; due tasks require operator review |
| `NOVA_SCHEDULER_INTERVAL_SECONDS` | Scheduler polling interval | `15`, bounded by settings validation |
| `NOVA_SEMANTIC_RETRIEVAL_ENABLED` | Optional local semantic retrieval | `false`; enable only after local embedding model validation |
| `NOVA_EMBEDDING_MODEL_PATH` | Local embedding model directory | `./data/models/embeddings` |
| `NOVA_HUGGINGFACE_CACHE_DIR` | Model metadata/download cache | `./data/models/huggingface`; monitor disk usage |
| `NOVA_HUGGINGFACE_MAX_DOWNLOAD_BYTES` | Download byte cap | `20000000000`; adjust to available disk space |
| `NOVA_HUGGINGFACE_TOKEN` / token file | Optional gated repository access | Never commit; keep owner-only permissions and redact from diagnostics |
| `NOVA_MCP_SANDBOX_MODE` | MCP stdio launch containment | `off`; Linux option `bwrap-readonly-root` requires bubblewrap and fails closed if unavailable; not a complete sandbox |
| `NOVA_WHISPER_CLI_PATH`, `NOVA_WHISPER_MODEL_PATH` | Optional local speech-to-text | Off unless binary/model are installed and validated |
| `NOVA_PIPER_CLI_PATH`, `NOVA_PIPER_MODEL_PATH` | Optional local text-to-speech | Off unless binary/model are installed and validated |
| `NOVA_FFMPEG_CLI_PATH` | Optional audio conversion | Empty unless installed |
| `NOVA_TESSERACT_CLI_PATH` | Optional OCR | Empty unless installed |
| `NOVA_PDF_OCR_ENABLED` | Enable scanned-PDF OCR | `false`; requires local renderer and OCR dependencies |
| `NOVA_PDF_RENDERER_CLI_PATH` | PDF page renderer | Empty unless installed |
| `NOVA_PDF_OCR_MAX_PAGES` | Maximum pages for OCR | `10`, bounded 1–50 |
| `NOVA_PDF_OCR_TIMEOUT_SECONDS` | PDF OCR timeout | `180`, bounded by settings validation |
| `NOVA_OCR_TIMEOUT_SECONDS` | Image OCR timeout | `60` |
| `NOVA_OCR_MAX_UPLOAD_BYTES` | Image upload cap | `15000000` bytes |
| `NOVA_ONNXRUNTIME_ENABLED` | Optional ONNX helper availability | `true`; does not make arbitrary ONNX models chat-capable |
| `NOVA_LLAMA_CPP_SERVER_PATH` | Optional separate runtime binary | Empty; not a silent chat fallback |
| WhatsApp-specific settings | Optional text bridge credentials/model ID | Keep secrets local; disable when not needed; never expose tokens in UI/logs |

The authoritative defaults and numeric bounds are the `Settings` model in `backend/nova/config.py` and the sample values in `.env.example`. If this table and code disagree, update the documentation in the same change as the code.

## 4. Settings UI requirements

Every setting surfaced in the web UI should include:

1. Human-readable purpose and current effective value.
2. Source: default, `.env`/process environment, or persisted user preference.
3. Validation message and allowed range/enum.
4. Whether a restart is required.
5. Safe reset-to-default action where appropriate.
6. Secret masking and no secret echo in API responses, exports, audit events or logs.
7. Clear separation between feature preference and security policy; a user preference must not override server-side authorization.
8. A visible dependency/preflight state for optional model/binary/runtime features.

## 5. Required regression gates for every new feature

- Backend unit/API tests: valid input, malformed input, unauthorized access, disabled feature, timeout, cancellation, size caps and error mapping.
- Security tests: traversal/symlink, SSRF/redirect, secret redaction, prompt-injection boundary, approval binding and audit event coverage.
- Frontend tests: navigation, form validation, persistence, empty/loading/error states, destructive confirmation and keyboard/mobile interaction.
- Integration tests: fake local server plus at least one real-server test before claiming broad interoperability.
- Operations: clean install, backup/restore, update/rollback, offline behavior and missing-dependency behavior on supported hosts.

## 6. Completion policy

A row is complete only when implementation, tests, UI/settings wiring, documentation and acceptance evidence exist. Do not mark a capability complete because a page, toggle, catalog entry or configuration schema exists. Do not advertise multi-user security, full MCP sandboxing, universal semantic RAG, arbitrary model-format inference, unrestricted autonomy or production readiness until the corresponding implementation and validation are complete.
