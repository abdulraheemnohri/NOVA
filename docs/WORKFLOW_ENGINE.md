# Workflow Engine

The persisted local workflow engine uses `/api/workflows`. The **Workflow Engine** dashboard page can create bounded definitions, run them, refresh execution history, and request cancellation for running instances.
- `GET /api/workflows`: list saved definitions.
- `POST /api/workflows`: save a named workflow with 1–10 structured steps.
- `POST /api/workflows/{workflow_id}/run`: run a definition after whole-plan preflight.
- `GET /api/workflows/runs?limit=20`: inspect recent runs.
- `GET /api/workflows/runs/{run_id}`: inspect one run and its per-step history.
- `POST /api/workflows/runs/{run_id}/cancel`: request cancellation of a currently running workflow.

Each step contains `tool`, strict `input`, and `when`: `always`, `on_success`, or `on_failure`. Conditions are checked against the most recent executed step; skipped steps do not change that outcome. Failures are recorded and may trigger a later failure branch, but the overall status remains `completed_with_errors` so recovery does not erase the original failure.

Only the bounded calculator and local knowledge-search primitives are allowed. Shell, network access, writes, and arbitrary generated code are unavailable. Definitions are revalidated before each run. Definitions, per-step checkpoints, run history, and audit events are stored locally.

Runs execute synchronously in the API process. Cancellation is persisted and checked between primitive calls; an already-running primitive is allowed to finish, and unstarted steps are not run. Checkpoints are written after each step, but the engine does not claim distributed-worker behavior or exactly-once execution if the process dies during a primitive call.


## Crash recovery

At application startup, NOVA marks workflow runs still recorded as `running` as `interrupted`, sets their finish/update timestamps, and writes an audit event for each run. It preserves recorded step checkpoints and deliberately does not resume or replay unfinished steps, because a crash may occur after a side effect but before the checkpoint is persisted. An operator can inspect the run through `GET /api/workflows/runs/{run_id}` and explicitly create a new run after reviewing the outcome.
