# MCP Runtime

NOVA supports explicitly managed MCP servers over two transports:

- **stdio:** NOVA starts a local child process with an argument array (never a shell).
- **Streamable HTTP:** NOVA sends bounded JSON-RPC requests to a configured HTTP(S) endpoint. HTTPS is required for remote hosts; plain HTTP is accepted only for loopback testing/local services.

## Workflow

1. Add an MCP definition in Integrations.
2. For stdio, review the executable, arguments, environment mapping, and filesystem/database scope. For Streamable HTTP, enter the endpoint and optionally the name of an environment variable containing a bearer token.
3. Enable the configuration and click **Connect**. Servers are not automatically started at application launch.
4. Review discovered tool names and descriptions before invoking them.
5. Tools annotated with MCP `readOnlyHint=true` can be invoked directly. Other tools require an explicit operator confirmation.
6. Disconnect when finished. NOVA shuts down managed sessions during graceful application shutdown.

## API

- `POST /api/integrations/mcp/{id}/connect`
- `GET /api/integrations/mcp/{id}/status`
- `GET /api/integrations/mcp/{id}/tools`
- `POST /api/integrations/mcp/{id}/tools/{tool_name}/call` with `{"arguments": {}, "confirm_side_effects": false}`
- `POST /api/integrations/mcp/{id}/disconnect`

## Transport controls

- stdio request timeout: 30 seconds; remote HTTP request timeout: 15 seconds.
- Request bodies are limited to 64 KB, response bodies to 1 MB, and discovery to 250 tools.
- Remote HTTP redirects are rejected to prevent credential forwarding to a different host.
- Remote bearer credentials are read from an environment variable named in `bearer_env`; secret values are not stored in SQLite.
- JSON-RPC lifecycle and tool actions are audit logged. Error messages avoid logging request bodies, auth headers, or remote response bodies.
- Remote MCP servers must support the Streamable HTTP JSON-RPC pattern. Servers that only support legacy SSE transport are not supported by this adapter.

## Security boundaries

- MCP servers are arbitrary programs. Stdio processes run with NOVA's operating-system permissions; this is **not a sandbox**. Use a dedicated low-privilege account and narrow filesystem/database scopes.
- Remote MCP is a network capability. Only connect endpoints you trust. HTTPS certificate validation is enabled by the standard Python TLS stack; redirects are rejected. The current implementation does not implement OAuth discovery/refresh or arbitrary custom headers.
- MCP tool annotations are server-supplied metadata, not proof that a tool is safe. Side-effect confirmation is an operator safeguard, not a sandbox.
- The browser-facing NOVA API remains loopback-only. Do not expose it to a LAN or public internet without authentication and a separate security review.
- API-provider definitions are still configuration-only. This MCP runtime does not add cloud inference or change the LiteRT-LM-only chat inference path.
