# MCP Runtime

NOVA supports explicit, operator-managed MCP connections over **stdio** and **Streamable HTTP**. Both transports share the same connect/status/tool-discovery/call/disconnect API and require explicit confirmation for tools that are not annotated read-only.

See [MCP Streamable HTTP and stdio runtime guide](MCP_STREAMABLE_HTTP.md) for setup, API routes, limits, authentication, security boundaries, and known limitations.

The runtime does not automatically start configured servers, add MCP tools to the model's chat tool catalog, or bypass the local tool policy. By default, MCP child processes run with the NOVA backend user's OS permissions. On Linux, operators may set `NOVA_MCP_SANDBOX_MODE=bwrap-readonly-root` to launch stdio children through `bubblewrap` with a read-only host-root mount, a writable NOVA workspace, and a temporary `/tmp`; if bubblewrap is unavailable or the sandbox cannot start, connection fails rather than silently falling back. The default `off` mode preserves compatibility. This is write-containment defense-in-depth, **not a complete security sandbox**: processes may still read host files visible inside the mount namespace and may use the network. Run NOVA as a dedicated low-privilege OS account and limit workspace contents. Remote endpoints use HTTPS except loopback development endpoints; bearer secrets are referenced through environment variables and are never persisted in integration configuration.

API-provider records in Integrations remain configuration-only. This runtime does not add cloud inference or alter the LiteRT-LM-only chat inference path.
