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
- `PUT /settings/preferences`: validate and persist `chat_max_tokens` (64–4096), `chat_temperature` (0.0–1.5; default 0.2), `auto_refresh_seconds` (0–300; 0 disables polling), and `confirm_model_selection` (boolean). Unknown fields are rejected. The saved temperature is applied to each LiteRT-LM chat request.
- Preference changes are stored in the local SQLite settings table and appended to the audit chain. These preferences cannot change the inference runtime, network binding, tool allowlist, or weaken approval policy.


## Chat retrieval and source metadata
`POST /chat` performs local keyword retrieval against indexed document chunks before inference. When matches exist, bounded excerpts are included in the prompt with an explicit untrusted-data warning; the response returns a separate `sources` array containing document/chunk IDs and lexical overlap scores. Scores are not calibrated confidence values, and this is not semantic/vector RAG. The model can still make unsupported claims; inspect source excerpts before relying on an answer.


## Self-created skills and safe tool proposals
- `GET /self/skills`, `POST /self/skills`, `POST /self/skills/{id}/activate`: persist and explicitly activate user-reviewed skill instructions. Instructions are stored as data and are not interpreted as code.
- `GET /self/tools`, `POST /self/tools`, `POST /self/tools/{id}/review`: list, propose, and review tools limited to existing calculator and local knowledge-search primitives with exact fixed schemas. Review does not register new capabilities or execute generated code.
- These endpoints are under `/api`; the normal local bearer-token and audit-integrity middleware applies.


## Controlled skill execution
- `POST /self/skills/{skill_id}/run` accepts 1–5 structured steps; current primitives are `calculator` (`expression`) and `knowledge_search` (`query`). All steps are preflighted before execution. Only active skills can run.
- `GET /self/skills/{skill_id}/runs` returns recent persisted run history. Run instructions are not executed as code; the caller supplies structured steps explicitly.


## Visual workflow builder
The Self-Improvement Lab provides an ordered workflow builder for active skills. Operators can compose up to five calculator and local knowledge-search steps, reorder or remove them, then submit the explicit structured plan to the controlled skill-run endpoint. The entire plan is preflighted before execution; arbitrary code, shell, network, and write tools are not available. Workflow definitions in this UI are client-side drafts; execution history is persisted by the backend.


## Persisted workflows
- `GET /self/workflows` lists up to 200 saved workflows.
- `POST /self/workflows` stores a named ordered plan bound to an active skill. Request shape: `{ "skill_id": "...", "name": "Research arithmetic", "steps": [{"tool":"calculator","input":{"expression":"6 * 7"}}] }`.
- `POST /self/workflows/{workflow_id}/run` reruns a saved plan through the same whole-plan preflight and existing safe primitive allowlist. Execution records remain available through the skill's run-history endpoint. Saved plans are persisted in SQLite and creation/execution are audited.


## Checkpointed skill and workflow execution
- Each controlled skill run persists completed step results and a current_step checkpoint after every safe primitive.
- POST /self/skills/{skill_id}/runs/{run_id}/cancel requests cooperative cancellation for a currently running execution. Cancellation is checked between steps; a step already executing may finish.
- GET /self/skills/{skill_id}/runs exposes status, completed results, checkpoint, and cancellation flag. Cancelled runs retain completed results for inspection and are not automatically replayed.
- Only the existing calculator and local knowledge-search primitives are allowed; whole-plan preflight remains mandatory. A checkpoint is progress evidence, not an instruction to replay side effects.


## Interrupted skill run recovery
- Startup recovery marks skill runs left in running state as interrupted while preserving their last committed checkpoint; it does not automatically replay any step.
- POST /self/skills/{skill_id}/runs/{run_id}/resume accepts only interrupted or failed runs, revalidates the complete saved plan, and continues from the checkpoint. The checkpoint must match the number of persisted results.
- Cancelled runs are intentionally not resumable through this endpoint. Resume is operator-triggered, and the current allowlist remains calculator and local knowledge search only.


## Bounded workflow retries
- Skill steps may set `retries` from 0 to 3 (default 0), representing additional attempts after the first attempt. The full workflow is preflight-validated before execution.
- Each attempt is persisted to run history and included in audit metadata. Exhaustion marks the run failed while preserving prior successful checkpoints and attempt history. Explicit resume revalidates the complete plan and retries the first incomplete step; it never happens automatically.
- Only the existing calculator and local knowledge-search primitives are allowed; retry budgets cannot exceed three retries per step.


## Citation verification
- POST /api/citations/verify accepts a query and 1–20 citations, each with a local chunk_id and quoted text.
- The endpoint verifies that each chunk belongs to an imported local document and that the normalized quote appears verbatim in that chunk. It records an audit event.
- This is deterministic source/quote validation, not semantic claim-entailment verification. Clients must not treat grounded=true as proof that a broader claim logically follows from the quote.


## Interrupted approval recovery
- Startup changes approvals left in `consuming` to `interrupted` and emits an `approval.recovery.interrupted` audit event.
- This state is quarantined, not retried automatically: a crash can occur before or after a filesystem change, so inspect the workspace and retained snapshots before taking further action.


## Runtime API discovery and configuration

- Fetch the live OpenAPI schema from `GET /openapi.json` and interactive API docs from `/docs` on the local backend. These reflect routes registered by the running version; clients should not assume every optional runtime is installed.
- Use the authenticated helper for terminal calls: `bash scripts/nova-api.sh GET /api/health`. It reads the local token file and accepts loopback API URLs only.
- Operator UI preferences are available at `GET/PUT /api/settings/preferences`. Runtime paths, inference endpoint, authentication and security policy are environment-controlled with `NOVA_*` settings; edit the local `.env` and restart the backend to apply them. Do not expose secrets in frontend settings or commit them.
- The web UI deliberately cannot edit bind addresses, authentication secrets, tool permissions or approval policy. These controls are not dynamically mutable through the preferences endpoint.
- Review `docs/DEVELOPMENT.md` for the opt-in Linux systemd user service installer. It does not apply to Windows or macOS.


## Bounded local text analysis tool
- `GET /agent/tools` lists registered safe primitives and their fixed input schemas.
- `POST /agent/tools/execute` supports `text_stats` with `{"name":"text_stats","input":{"text":"..."}}`; it returns character, word, and line counts for up to 10,000 characters. This operation is local, deterministic, and read-only.
- Active self-created skills can use the same `text_stats` primitive in explicit structured workflow steps. All steps are preflighted before execution, and generated code is never run.

## Safe local utility tools

`GET /api/agent/tools` returns the registered tool catalog and input schemas. `POST /api/agent/tools/execute` accepts `{"name":"...","input":{...}}` and only runs registered tools allowed by the default-deny policy. Utility tools include `calculator`, `text_stats`, `json_format`, `base64_encode`, and `base64_decode`; `knowledge_search` queries local knowledge. Inputs are size-bounded, failures are audited, and unknown tools are denied. The catalog does not imply shell, arbitrary network, or file-write access.


## Additional read-only analysis tools
- `POST /api/agent/tools/execute` supports `csv_summary` with `{"name":"csv_summary","input":{"csv":"name,age\\nA,20"}}`. It returns bounded row/column counts and per-column missing-value counts plus conservative type hints. Input is limited to 100,000 characters, 2,000 rows and 100 unique columns; malformed/duplicate headers are rejected.
- `POST /api/agent/tools/execute` supports `markdown_outline` with `{"name":"markdown_outline","input":{"markdown":"# Title\\n## Section"}}`. It returns heading levels, text and source line numbers for up to 500 headings and 100,000 input characters.
- Both tools are deterministic, local, read-only, policy-registered and audit logged. They do not execute document content, access the network, or write files.


## Dynamic runtime feature controls
- `GET /settings/features` reads persistent, audit-logged capability switches.
- `PUT /settings/features` validates and saves `local_retrieval_enabled`, `model_hub_enabled`, `model_downloads_enabled`, `whisper_enabled`, `piper_enabled`, `ocr_enabled`, `onnx_runtime_enabled`, and `max_model_download_bytes`.
- These switches take effect at request time for local retrieval, Hugging Face search/file browsing/downloads, Whisper transcription, Piper synthesis, image OCR, and ONNX runtime discovery. Turning a feature off blocks new operations; it does not uninstall packages, remove models, or stop a currently-running external process.
- The configured model-download byte limit is additionally capped by `NOVA_HUGGINGFACE_MAX_DOWNLOAD_BYTES`; the UI cannot raise the environment-defined hard ceiling.
- These settings do not change the LiteRT-LM-only chat policy, API authentication, audit enforcement, workspace write approvals, or network binding.


## Dynamic runtime features and LiteRT-LM startup
- `GET /settings/features`, `PUT /settings/features`: read/update persisted runtime switches for local retrieval, Hugging Face browsing, downloads, Whisper, Piper, OCR and ONNX discovery. Updates are audit-logged and enforced by backend handlers.
- `GET /runtimes/litert/autostart`: inspect Linux systemd user-service support, configuration presence, enabled and active status.
- `PUT /runtimes/litert/autostart` with `{"enabled":true,"enable_linger":false}`: create and start an opt-in user service. Requires Linux + systemd, the project virtual environment, and an operator-configured `NOVA_LITERT_LM_COMMAND` in local `.env`. `enable_linger` is optional and may be denied by OS policy. Set `enabled:false` to stop/disable and remove the unit.
- The service launcher tokenizes the configured command and uses `execvpe` (no shell). Operators must verify the release-specific command binds to loopback and matches `NOVA_LITERT_BASE_URL`; NOVA does not guess flags, download model weights, or assert device compatibility.
