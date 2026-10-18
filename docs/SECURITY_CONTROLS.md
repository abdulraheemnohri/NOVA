# API security controls

NOVA applies defense-in-depth controls to its local API:

- Bearer-token authentication and audit-chain fail-closed behavior remain mandatory.
- A SQLite-backed sliding-window request budget limits each client address to 120 API requests per minute by default. Request and failed-authentication counters survive process restarts and are shared by workers using the same database. Client identifiers are stored as SHA-256 hashes rather than raw addresses.
- Failed authentication has a separate budget: ten failures within five minutes block that client for one minute.
- The API does not trust `X-Forwarded-For` or similar headers. The direct peer address is used, preventing callers from spoofing their own rate-limit identity.
- API responses include basic browser hardening headers and `Cache-Control: no-store`.

## Scope and limitations

The limiter is intentionally dependency-free and works for the default single-process, loopback deployment. Its counters are in memory and are not shared between worker processes or hosts. Before exposing NOVA to a LAN, reverse proxy, or multiple users, deploy a trusted edge limiter, restrict network access, and implement user identities/roles and per-user quotas. This change does not claim to implement multi-user RBAC, encrypted database storage, or production OS sandboxing.

Tune the limits in `LocalRateLimiter` only with test coverage. Health checks remain rate-limited to avoid an unauthenticated endpoint becoming a trivial resource-exhaustion vector.
