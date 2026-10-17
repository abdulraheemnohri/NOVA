# Security Model

Model output is untrusted and cannot authorize itself. Backend tool policy defaults to deny. Writes require an approved record matching the exact registered action. Paths are resolved and constrained to the workspace. The inference adapter rejects non-loopback endpoints and never falls back to another runtime.

Audit records form a SHA-256 hash chain. This detects ordinary edits but is not immutable against a privileged administrator who can rewrite the log and recompute hashes. Periodically sign/export checkpoints to independently controlled media for stronger evidence.

**Known gaps:** no API authentication/RBAC yet; bind to localhost only. Approval records are a prototype until user identity is enforced. Snapshots cover previous file contents but are not a complete recovery system. No arbitrary shell or code execution tool is enabled. Prompt-injection scanning, encrypted storage, document RAG, memory, and production sandboxing are not complete.
