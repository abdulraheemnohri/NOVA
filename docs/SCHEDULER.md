# Local Scheduler

NOVA's scheduler is intentionally conservative. A task is eligible when its timezone-normalized `due_at` is at or before UTC now and its state is `queued`. The scheduler claims eligible tasks in a SQLite `BEGIN IMMEDIATE` transaction, with a 60-second lease, and moves them to `planned`. Priority order is urgent, high, normal, then low.

## Safety contract

- A successful dispatch means **planned for operator review**, not executed.
- No shell, browser, filesystem write, model-generated plan, or external tool is run by the scheduler.
- Background polling is disabled by default. Set `NOVA_SCHEDULER_ENABLED=true` to enable it; `NOVA_SCHEDULER_INTERVAL_SECONDS` defaults to 15 seconds.
- The authenticated `POST /api/scheduler/run-once` endpoint manually runs one pass even when the background worker is disabled.
- `GET /api/scheduler/status` reports configuration, due backlog and active leases.
- Claims expire after 60 seconds. A later pass can recover expired claims. Retry metadata is bounded to five claims; unexpected dispatch errors are recorded and audit logged.
- All API calls require the local bearer token and a valid audit chain, except public health and audit verification routes.

## Settings and UI

Open **Scheduler** in the local dashboard to inspect worker status, edit the opt-in worker toggle and poll interval, and run one pass. Settings are persisted in the local SQLite database and loaded on startup; environment variables provide initial defaults until the operator saves settings. The screen explicitly reports that tool execution is not enabled.

## Not yet implemented

This is not a general job runner and does not execute arbitrary tasks. Approval-bound tool execution, process isolation, per-task cancellation while a tool is running, and OS-level sandboxing remain separate security milestones.
