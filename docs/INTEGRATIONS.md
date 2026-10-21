# NOVA integrations

The **Integrations** workspace provides a local SQLite registry for:
- MCP server definitions using local stdio or remote Streamable HTTP transports.
- Online tool links and existing search adapters.
- External API provider metadata (base URL, authentication type, and environment-variable reference).

## Important current limitation

The current release implements configuration CRUD, validation, audit events, and a catalogue of common open-source templates. It does **not yet launch stdio processes, perform MCP tool discovery/calls, or execute arbitrary third-party API calls**. An enabled configuration is a saved preference, not proof that a server is installed, connected, or running.

Browse the [official MCP Registry](https://registry.modelcontextprotocol.io/) for the broader server directory. The registry contains both free and paid offerings; verify each project's licence, maintenance status, dependencies, and service/API limits.

## Local configuration API

- `GET /api/integrations/catalog` — curated templates.
- `GET|POST /api/integrations/mcp`, `PATCH|DELETE /api/integrations/mcp/{id}` — MCP definitions.
- `GET|POST /api/integrations/online-tools`, `PATCH|DELETE /api/integrations/online-tools/{id}` — online tool links.
- `GET|POST /api/integrations/apis`, `PATCH|DELETE /api/integrations/apis/{id}` — API provider definitions.

All endpoints remain protected by NOVA's loopback-only API middleware and audit-chain checks. Configuration records are stored in the existing local SQLite database.

## Credential and transport rules

- Never store secret values in configuration JSON. Store an environment-variable **name** such as `MY_SERVICE_API_KEY`; supply the value through the local process environment separately.
- Remote endpoints must use HTTPS. Plain HTTP is allowed only for loopback MCP endpoints and loopback API base URLs.
- Local stdio commands are saved as definitions only. Do not enable arbitrary process execution without per-server isolation, explicit allowed directories, resource limits, approval gates, timeouts, and output-size limits.
- Treat all MCP tool results and remote content as untrusted input. Prefer read-only database access and narrow filesystem scopes.
- Public services may require accounts, API keys, paid plans, or impose rate limits even if their client/server package is open source.
