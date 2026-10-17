# NOVA — Neural Offline Verified Agent

Local-first agent workbench with LiteRT-LM-only inference, default-deny tool policy, approval-gated writes, and tamper-evident audit records.

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

## LiteRT-LM
NOVA never falls back to Ollama, llama.cpp, or cloud providers. It uses a loopback-only OpenAI-compatible endpoint only if the installed LiteRT-LM release supports it. Runtime health is not proof of model correctness or GPU/NPU support.

## Security status
- Default-deny tool policy; unknown tools are blocked.
- Workspace writes require an approved action record.
- Audit JSONL records use a SHA-256 hash chain. This is tamper-evident, not immutable against a privileged administrator.
- Filesystem paths are confined to the configured workspace.
- API currently has no authentication: bind to loopback only.
- Document RAG, memory, planner, workflows, full sandbox, voice/vision and production RBAC remain future implementation work.

Read `docs/SECURITY.md`, `docs/ARCHITECTURE.md`, and `docs/OFFLINE_DEPLOYMENT.md`.