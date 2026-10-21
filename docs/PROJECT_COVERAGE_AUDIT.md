# NOVA Project Coverage Audit

**Audit date:** 2026-10-21  
**Repository:** `abdulraheemnohri/NOVA`  
**Audited base:** `main` at `5a2beed2725fbf3f0b803fabc8c2970a191207ff`

This is a source-tree and route-wiring audit, not a claim that every feature has been exercised on a real host. CI and hardware-specific validation must be recorded separately.

## Summary

NOVA already has a substantial local-first backend and web UI. The main verified issue found in this pass was a navigation target named **Agent Console** that had no dedicated render branch; the dashboard quick action pointed to it and therefore displayed the dashboard rather than opening chat. The route was corrected in the companion change: the duplicate navigation item was removed and the quick action now opens **Chat**.

The MCP stdio runtime was **not present on the audited main SHA**. It exists in the separate PR #148 branch and should only be integrated after its latest CI run is green and runtime security/tests have been reviewed.

## Frontend page inventory

The main navigation contains these work areas:

| Page | Current scope found in source | Review notes |
|---|---|---|
| Dashboard | Health, LiteRT reachability, audit integrity, approvals, runtime inventory, AI capability status, quick actions | Quick action route corrected to Chat |
| Chat | Private/Public mode, local conversation persistence, history search, archive/restore, deletion, JSON/Markdown export, attachments, voice input/output where browser supports it, optional public web search | Private mode must remain offline-only at both UI and backend enforcement layers |
| Agent Workbench | Agent workbench controls | Validate every action against backend allowlist/approval policy |
| Self-Improvement Lab | Self-improvement, skills and tool-proposal workflows | Generated skills/proposals must remain untrusted until reviewed/tested |
| Workflow Engine | Workflow definitions/execution tracking/recovery | Do not describe it as unrestricted autonomous execution |
| Updates | Update inspection/application workflow | Updates need explicit review, backups and rollback tests |
| WhatsApp Agents | Optional WhatsApp Agent Platform text integration | External service; no cloud inference fallback; sensitive-message warning required |
| Online AI & Search | Online tool/search entry points | This page is separate from API/provider configuration |
| Integrations | MCP configuration, online tools, API provider configuration | Configuration is not equivalent to an executable provider/runtime |
| Model Manager | Local model registry, active/inactive state, preflight, selection, discovery, device profile | Only compatible registered `.litertlm` models are chat-selectable |
| Hugging Face | Metadata search, file listing, bounded downloads, local token/cache status | Internet required for search/download; never execute downloaded repository code |
| Knowledge Base | Local document retrieval/search and citation checks | Lexical retrieval is available; semantic retrieval is opt-in/limited |
| Documents | Import and manage indexed documents | Verify extraction behavior for supported document types on target host |
| Goals | Local goals and status | Goal completion must not silently grant new permissions |
| Tasks | Local task queue and status transitions | Tasks are operator-authored; the scheduler does not execute arbitrary plans |
| Scheduler | Due-task scheduling controls/status | Current behavior moves due tasks to Planned for operator review |
| System Monitor | Host/resource telemetry, best-effort mobile/Android data | Hardware counters may be unavailable depending on OS/kernel |
| Diagnostics | Runtime/API/model and audit diagnostics | Diagnostics should stay read-only |
| Runtimes | Runtime inventory and optional task-scoped runtime controls | Optional runtimes are not automatic chat fallbacks |
| Memory Manager | Local memory CRUD and categories | Needs clear retention/export/delete behavior and privacy boundaries |
| Approvals | Pending/approved/rejected action queue | Decisions must remain payload-bound and audited |
| Audit & Safety | Audit verification and workspace snapshots/rollback | Hash chain is tamper-evident, not immutable against a privileged administrator |
| Settings | Preferences, bounded feature switches, AI capability switches, live status, effective non-secret configuration | Security-critical settings stay environment-managed/human-only |
| About | Project status/help | Keep limitations aligned with implementation and README |

**Separate Chat History page:** history currently appears as a mode inside Chat, not as a top-level navigation item. It supports search, reopening, archive/restore, export and permanent deletion.

## Backend modules and API areas found

- **Core API and auth:** `backend/nova/main.py`, health endpoint, bearer-token protection for protected routes, rate limiting and local-only deployment guidance.
- **Chat storage:** `backend/nova/chat_store.py` with conversation create/list/update/delete, message CRUD, export/import and attachment routes.
- **Local inference:** `backend/nova/litert.py`; LiteRT-LM is the only chat inference path and there is no cloud fallback.
- **Models:** `backend/nova/model_manager.py`, `backend/nova/huggingface.py`, `backend/nova/hardware_profile.py`.
- **Tool policy and approvals:** `backend/nova/agent_tools.py`, `backend/nova/policy.py`, `backend/nova/security.py`.
- **Audit and recovery:** `backend/nova/audit.py`, workspace snapshots/rollback, run/workflow recovery modules.
- **Knowledge and search:** `backend/nova/knowledge.py`, `backend/nova/web_search.py`, `backend/nova/duckduckgo_search.py`.
- **Integrations configuration:** `backend/nova/integrations.py` for catalog and CRUD of MCP, online-tool and API-provider definitions.
- **Settings:** `backend/nova/settings_preferences.py` and environment-backed configuration.
- **Operational modules:** diagnostics, runtime inventory/lifecycle, tasks, scheduler, workflow engine, self-improvement, system monitor, updates and WhatsApp.

## Confirmed or documented limitations to track

These are not silently marked complete; they need a distinct implementation and tests if they are to become supported product capabilities.

1. **MCP execution on main:** stdio runtime is in PR #148, not in the audited main tree. The PR explicitly does not implement remote Streamable HTTP MCP transport.
2. **API-provider execution:** provider definitions/configuration exist, but arbitrary configured API-provider execution is not established by the current Integrations CRUD API.
3. **Remote MCP transports:** Streamable HTTP/SSE transport, remote authentication refresh and connection lifecycle are not part of MCP stdio V1.
4. **Process sandboxing:** configured MCP child processes run with the NOVA backend user's OS permissions; this is not a sandbox. Use a low-privilege OS account and narrow workspace scope.
5. **Multi-user RBAC:** the current security model is one local operator bearer token, not per-user roles or account isolation.
6. **Semantic RAG:** lexical local retrieval is available; full semantic/vector retrieval should not be described as universally enabled or production-complete.
7. **Non-LiteRT model execution:** GGUF, ONNX, TFLite and Safetensors can be inventoried/downloaded as supported by the manager, but they are not general-purpose chat runtimes in the current architecture.
8. **Autonomous task execution:** the task scheduler does not execute arbitrary task plans or generated shell commands. Due tasks are staged for operator review.
9. **Real-device validation:** LiteRT-LM CLI/server compatibility, model loading, speech/OCR binaries, mobile device counters and offline smoke tests require tests on each target OS/device.
10. **Frontend routing regression tests:** add automated coverage so every visible navigation item and quick action maps to an intentional render target.

## Required acceptance checks for future feature work

- Backend: unit and API tests; malformed input and auth checks; path traversal/symlink boundaries; timeout/cancellation; concurrent updates; audit events; disabled-feature behavior.
- Frontend: unit tests for route targets, empty/loading/error states, form validation, persistence, destructive confirmations and keyboard/mobile navigation.
- Privacy: private chat must not call web search, external APIs, MCP or online tools; test at the backend boundary, not only by hiding UI controls.
- Integration security: never store plaintext provider secrets in config rows; use environment-variable references or owner-only secret files; redact secrets from logs/status.
- Runtime safety: MCP subprocesses use argument arrays (never shell concatenation), explicit environment references, bounded output/timeouts, explicit confirmation for side effects, and shutdown cleanup.
- Release gate: CI green on the exact PR head SHA; review changed files and permissions; real-host smoke tests before calling the release production-ready.

## Suggested implementation order

1. Merge the MCP stdio runtime only after CI is green and code review is complete.
2. Add route/quick-action tests and a frontend page coverage assertion.
3. Add server-side tests proving Private Chat cannot invoke online integrations regardless of request payload.
4. Add conversation retention/export/import edge-case tests, including attachment cleanup and delete semantics.
5. Add explicit provider adapters one at a time (with per-provider timeouts, secret references, allowlisted capabilities and tests); do not infer support from saved configuration alone.
6. Add remote MCP transport only with separate threat modeling and transport/auth tests.
7. Implement optional sandboxing and multi-user authorization as separate security projects.
8. Keep README, settings guide, API docs, UI labels and actual behavior synchronized.

## Audit confidence

- **Source tree/routes:** inspected on the stated main SHA.
- **Feature behavior:** only considered implemented where code paths were found; this audit does not replace test execution.
- **CI:** use the linked GitHub Actions runs for the exact head SHA. A queued/running job is not a passing result.
- **Production readiness:** not asserted.
