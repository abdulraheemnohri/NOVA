# NOVA — Neural Offline Verified Agent

Local-first agent workbench with LiteRT-LM-only inference, default-deny tool policy, approval-gated writes and rollbacks, bearer-token-protected local API routes, and tamper-evident audit records.

## Status
This is the initial engineering foundation, not a feature-complete production release. Runtime commands, endpoint compatibility, model IDs, and hardware acceleration must be verified against the installed LiteRT-LM version.

## Debian quick start
```bash
sudo apt install -y python3 python3-venv python3-pip nodejs npm
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
uvicorn nova.main:app --app-dir backend --host 127.0.0.1 --port 8000
```
In another terminal: `cd frontend && npm install && npm run dev`.

On first startup NOVA creates `data/api.token` with restrictive permissions. Open that file locally and paste its token into the Web UI sign-in screen. Do not share the token. The UI keeps it only for the current browser tab session. Keep the backend bound to loopback.

## LiteRT-LM
NOVA never falls back to Ollama, llama.cpp, or cloud providers. It uses a loopback-only OpenAI-compatible endpoint only if the installed LiteRT-LM release supports it. Runtime health is not proof of model correctness or GPU/NPU support.

## Security status
- Default-deny tool policy; unknown tools are blocked.
- Workspace writes and destructive rollback require explicit, payload-bound approval.
- All API routes except `/api/health` require a local bearer token.
- Audit JSONL records use a SHA-256 hash chain. This is tamper-evident, not immutable against a privileged administrator.
- Filesystem paths are confined to the configured workspace.
- Authentication is a single local operator token, not multi-user RBAC.
- Document RAG, planner, workflows, full sandbox, voice/vision, and production recovery remain future implementation work.

Read `docs/SECURITY.md`, `docs/ARCHITECTURE.md`, and `docs/OFFLINE_DEPLOYMENT.md`.
