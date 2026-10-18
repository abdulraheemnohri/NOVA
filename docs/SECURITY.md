# Security Model

Model output is untrusted and cannot authorize itself. Backend tool policy defaults to deny. Writes and destructive rollback require separate approved records tied to the exact action payload. Paths are resolved and constrained to the workspace; workspace paths and the internal snapshot store reject symbolic links. This reduces symlink escapes but is not a race-free filesystem sandbox; production deployments should use directory-file-descriptor/openat-style operations. The inference adapter rejects non-loopback endpoints and never falls back to another runtime.

## Hugging Face Hub access

Hub access is optional and only used when the operator searches or explicitly downloads an artifact. Set `NOVA_HUGGINGFACE_TOKEN` in the backend environment or local `.env` for gated/private repositories; the status endpoint exposes only whether a token exists, never the value. Requests begin at the official HTTPS Hugging Face host; redirects are restricted to HTTPS Hugging Face/CDN hosts, and the bearer token is not forwarded to external CDN hosts. Downloads are limited to selected artifact extensions and a configured maximum size, written atomically, hashed, and audit-logged. A checksum calculated locally is not proof of publisher authenticity unless compared with a trusted expected checksum. Treat all downloaded weights as untrusted data; repository code is not executed.

## Local API authentication

At startup, NOVA creates a cryptographically random bearer token at `data/api.token` (or the configured `NOVA_API_TOKEN_FILE`) if the file does not already exist. On POSIX systems the file is created with mode `0600` and permissions are reset to `0600` at startup. The token is never returned by an API endpoint. The Web UI asks the operator to paste it and keeps it in tab-scoped `sessionStorage`; use **Lock session** to clear it. `GET /api/health` remains public for local process supervision; other `/api/*` endpoints require `Authorization: Bearer <token>`. Rotate the token by stopping NOVA, securely replacing/removing the token file, and restarting the service. Keep the service bound to `127.0.0.1`; this token flow is local operator authentication, not a complete multi-user identity or role-based access system.

Audit records form a SHA-256 hash chain. This detects ordinary edits but is not immutable against a privileged administrator who can rewrite the log and recompute hashes. Periodically sign/export checkpoints to independently controlled media for stronger evidence. NOVA now verifies the chain before serving authenticated API actions and returns HTTP 503 when integrity is broken; `/api/health` and `/api/audit/verify` remain available for diagnosis. Appending to a damaged chain is refused. The current verification scans the JSONL history on each request/append, so very large logs will need checkpointing or a carefully designed indexed verification strategy.

**Known gaps:** authentication is single-token local access, not multi-user RBAC; approval records do not yet include a separately authenticated user identity. Approved writes and rollbacks are payload-bound and single-use, but concurrent-request race testing remains required. Workspace writes create versioned snapshots with unique IDs. Rollback restores previous file bytes or removes a newly created file and marks a snapshot as used. This is not a complete system recovery mechanism; filesystem durability, concurrent writers, and crash-recovery behavior still need deeper testing. No arbitrary shell or code execution tool is enabled. Prompt-injection scanning, encrypted storage, document RAG, and production sandboxing are not complete.


## Prompt context and retrieved content

The agent prompt keeps a fixed safety contract after operator profile and skill guidance. Enabled skills and retrieved local excerpts are serialized as JSON data so embedded newlines cannot impersonate surrounding prompt sections. This is a formatting boundary, not a guarantee against model prompt injection: retrieved text remains untrusted, tool permissions are enforced by backend policy, and arbitrary shell/code execution remains disabled. Continue to test adversarial documents and skills against each supported local model.


## Local inference response hardening

The LiteRT-LM adapter only accepts HTTP endpoints whose host is a literal loopback IP or `localhost`. Endpoint URLs containing embedded credentials, query strings or fragments are rejected. Redirects from the configured local endpoint are not followed, preventing a local service from redirecting the adapter to an external host. `/models` and chat responses are read with strict byte limits; malformed or oversized responses fail closed. This is defense in depth, not a substitute for keeping the inference server bound to loopback and running it as an unprivileged user.

## WhatsApp webhook input limits

The inbound WhatsApp webhook verifies the `X-Hub-Signature-256` HMAC against the raw request bytes and rejects request bodies larger than 1 MB with HTTP 413 before JSON parsing. Keep the webhook reachable only when integrating with the WhatsApp Cloud API; signature validation and sender allowlisting are both required. The payload limit is an application-level cap and should be complemented by reverse-proxy/server request limits in public deployments.
