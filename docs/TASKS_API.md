# Task Queue API

All routes require the local NOVA bearer token and a valid audit chain.

- GET /api/tasks?status=queued&limit=100 — list tasks; status filter is optional.
- POST /api/tasks — create a task with title, optional description, priority (low, normal, high, urgent), optional ISO-8601 timezone-aware due_at, up to 50 human-authored plan steps, and max_attempts (integer 1–10, default 3).
- POST /api/tasks/{id}/status — apply a permitted lifecycle transition. Allowed states: queued to planned/cancelled; planned to queued/in_progress/cancelled; in_progress to completed/failed/cancelled; failed to queued/cancelled. Completed and cancelled are terminal.
- DELETE /api/tasks/{id} — delete a task unless it is in progress.

The API persists tasks in the existing local SQLite database and emits hash-chained audit events. Retries are bounded by max_attempts. Each transition to in_progress consumes one attempt; a task that reaches the limit cannot be started again or requeued from failed. Concurrent status changes are serialized in SQLite. Existing databases are migrated additively. Moving a task to in_progress only records lifecycle state; it does not execute code, run shell commands, or imply a worker exists. Due dates are metadata until a separately implemented scheduler is enabled.
