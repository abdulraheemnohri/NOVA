# NOVA integrations

The **Integrations** workspace provides a local SQLite registry for:
- MCP server definitions using local stdio or remote Streamable HTTP transports.
- Online tool links and existing search adapters.
- External API provider metadata (base URL, authentication type, and environment-variable reference).

## Important current limitation

The current release implements configuration CRUD, validation, audit events, a catalogue of common open-source templates, and an opt-in **stdio MCP runtime**. Enabled stdio definitions can be connected manually, discovered tools can be called, and tools not marked read-only require explicit side-effect confirmation. A saved configuration is not proof that a server is installed or running. Remote Streamable HTTP MCP runtime and bounded API-provider execution are now supported; see [MCP Runtime V1](MCP_RUNTIME_V1.md) and [API Provider Runtime](API_PROVIDER_RUNTIME.md). The Integrations page includes an explicit API request workbench for enabled providers; it is never automatically invoked by chat.

Browse the [official MCP Registry](https://registry.modelcontextprotocol.io/) for the broader server directory. The registry contains both free and paid offerings; verify each project's licence, maintenance status, dependencies, and service/API limits.

## Local configuration API

- `GET /api/integrations/catalog` — curated templates.
- `GET|POST /api/integrations/mcp`, `PATCH|DELETE /api/integrations/mcp/{id}` — MCP definitions.
- `GET|POST /api/integrations/online-tools`, `PATCH|DELETE /api/integrations/online-tools/{id}` — online tool links.
- `GET|POST /api/integrations/apis`, `PATCH|DELETE /api/integrations/apis/{id}` — API provider definitions.
- `POST /api/integrations/apis/{id}/request` — explicitly execute an allowlisted JSON request against an enabled provider.

All endpoints remain protected by NOVA's loopback-only API middleware and audit-chain checks. Configuration records are stored in the existing local SQLite database.

## Credential and transport rules

- Never store secret values in configuration JSON. Store an environment-variable **name** such as `MY_SERVICE_API_KEY`; supply the value through the local process environment separately.
- Remote endpoints must use HTTPS. Plain HTTP is allowed only for loopback MCP endpoints and loopback API base URLs.
- Local stdio commands execute only after an explicit Connect action, without a shell, and run with the NOVA backend user's OS permissions. This is not a sandbox; use a low-privilege account, narrow filesystem access, and reviewed commands. Runtime requests have timeouts and payload limits.
- Treat all MCP tool results and remote content as untrusted input. Prefer read-only database access and narrow filesystem scopes.
- Public services may require accounts, API keys, paid plans, or impose rate limits even if their client/server package is open source.
