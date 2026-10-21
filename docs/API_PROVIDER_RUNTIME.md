# API Provider Runtime (Initial)

NOVA's API integrations are explicit operator-configured actions, separate from chat inference. Private Chat continues to use the local LiteRT-LM path and cannot dispatch provider requests.

## Configure a provider

Create an API integration under `/api/integrations/apis` with a config like:

```json
{
  "base_url": "https://api.example.com",
  "auth_type": "bearer_env",
  "api_key_env": "NOVA_EXAMPLE_API_TOKEN",
  "allowed_paths": ["/v1/status", "/v1/items"],
  "timeout_seconds": 10,
  "max_response_bytes": 1048576
}
```

Set the referenced token in the backend process environment. Secrets are never accepted as config values and are not returned by the runtime. Enable the provider explicitly before execution.

## Execute

Send `POST /api/integrations/apis/{id}/request` with a JSON body:

```json
{"path": "/v1/status", "method": "GET"}
```

Only exact paths listed in `allowed_paths` are accepted. The runtime supports GET and JSON POST, with a 64 KiB request-body ceiling, 1–30 second timeout, 1 KiB–2 MiB response ceiling, JSON response validation, and redirect rejection. Remote base URLs must use HTTPS; HTTP is accepted only for loopback development services. Environment proxy settings are ignored by the HTTP client.

## Audit and privacy

Audit events include provider ID, method, allowlisted path, HTTP status, duration, and error type where applicable. They intentionally omit authorization headers, secrets, request payloads, and response bodies. API requests are not invoked by the Private Chat action parser and do not become an automatic inference fallback.

## Current limitations

- `none` and `bearer_env` are the only runtime authentication modes. `header_env` and `oauth_external` remain configuration-only.
- The runtime is generic JSON transport, not a provider-specific SDK. Configure only trusted API origins and narrowly scoped paths.
- It does not claim to prevent every network-level risk of an operator-configured host; deploy NOVA with least-privilege network access.
- Run CI and real-service compatibility tests before treating a provider as production-ready.
