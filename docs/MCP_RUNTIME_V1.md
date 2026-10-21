# MCP Runtime V1

NOVA can launch **explicitly enabled local stdio MCP servers** from the Integrations workspace. It starts the configured executable with `asyncio.create_subprocess_exec` (never a shell), performs MCP initialization, discovers tools, and exposes an operator-controlled tool-call UI.

## Workflow

1. Add a stdio server definition in Integrations and review its command, arguments, environment-variable references, and filesystem scope.
2. Enable the configuration.
3. Click **Connect** to start the child process. The server is not started automatically on application launch.
4. Review discovered tool names and descriptions.
5. Read-only tools marked with MCP `annotations.readOnlyHint=true` can be invoked directly. All other tools require checking the explicit side-effect confirmation.
6. Disconnect when finished. NOVA also terminates managed MCP child processes during graceful application shutdown.

## API

- `POST /api/integrations/mcp/{id}/connect`
- `GET /api/integrations/mcp/{id}/status`
- `GET /api/integrations/mcp/{id}/tools`
- `POST /api/integrations/mcp/{id}/tools/{tool_name}/call` with `{"arguments": {}, "confirm_side_effects": false}`
- `POST /api/integrations/mcp/{id}/disconnect`

Tool calls are JSON-RPC requests to the selected process. Each request has a 30-second timeout, request payloads are bounded, tool discovery is capped, and lifecycle/tool events are written to NOVA's audit chain. Stderr output is discarded rather than retained.

## Security boundaries and limitations

- MCP servers are arbitrary programs and run with the operating-system permissions of the NOVA backend user. Connect only commands and packages you trust. Process execution is not a sandbox.
- Use a dedicated low-privilege OS account, narrow filesystem/database scopes, and a reviewed command/argument list. Do not point a filesystem MCP server at the entire home directory or secrets.
- The browser-facing NOVA API remains loopback-only. Do not expose it to a LAN or the public internet without authentication and a separate security review.
- The runtime currently supports **stdio only**. Remote Streamable HTTP MCP connections are saved as configuration but return HTTP 501 at runtime.
- Tool annotations are server-supplied metadata, not proof that a tool is safe. The explicit confirmation is an operator safeguard, not a security sandbox.
- Arbitrary third-party API-provider execution and direct tool invocation from the chat planner are not yet implemented.
