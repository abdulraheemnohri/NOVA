# MCP Runtime

NOVA supports explicit, operator-managed MCP connections over **stdio** and **Streamable HTTP**. Both transports share the same connect/status/tool-discovery/call/disconnect API and require explicit confirmation for tools that are not annotated read-only.

See [MCP Streamable HTTP and stdio runtime guide](MCP_STREAMABLE_HTTP.md) for setup, API routes, limits, authentication, security boundaries, and known limitations.

The runtime does not automatically start configured servers, add MCP tools to the model's chat tool catalog, or bypass the local tool policy. MCP child processes are not sandboxed and run with the NOVA backend user's OS permissions. Remote endpoints use HTTPS except loopback development endpoints; bearer secrets are referenced through environment variables and are never persisted in integration configuration.

API-provider records in Integrations remain configuration-only. This runtime does not add cloud inference or alter the LiteRT-LM-only chat inference path.
