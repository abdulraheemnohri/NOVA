# WhatsApp Agent Platform — text-only V1

## Scope and platform distinction

NOVA uses Meta's WhatsApp Agent Platform endpoint `https://api.whatsapp.com/agent/v1`. This is **not** WhatsApp Web QR pairing and is **not** the WhatsApp Business Cloud API webhook bridge. It does not emulate consumer WhatsApp agent linking; availability and eligibility depend on Meta.

The integration is disabled by default. It accepts text-only messages from one explicitly allowlisted creator ID and routes replies to the local LiteRT-LM backend. It does not call remote inference APIs.

## 1. Configure in NOVA

1. Open **WhatsApp Agent Platform** in the NOVA Web UI.
2. Enter the Agent API key supplied by the relevant WhatsApp Agent Platform creator/agent settings. Treat it as a password.
3. Enter the exact creator WhatsApp sender/user ID documented by Meta for the account. Do not guess it or substitute a display name.
4. Save the key and ID. Enable the integration only after both are configured.
5. Use **Test connection** to check whether Meta accepts the key. The test restores the poll cursor.
6. Enable polling only when the local model is installed and verified.

The service never trusts the first inbound message as proof of identity. Messages from any sender other than the configured creator ID are ignored. Manual sends are restricted to the same creator ID.

## 2. Local Gemma / LiteRT-LM requirements

- Default model ID: `gemma-4-e4b`.
- The local LiteRT-LM endpoint must advertise the exact model ID NOVA uses.
- If the server advertises a different ID for the verified Gemma 4-E4B artifact, set `NOVA_WHATSAPP_AGENT_MODEL_ID` in the backend environment to that ID and restart NOVA.
- Model weights are installed separately; this integration does not download them.
- If the model is absent or not advertised, NOVA never silently falls back to cloud inference or another model.

A successful API-key test does not prove Gemma inference works.

## 3. Local storage and security

- State and API key are stored under the NOVA data directory in `whatsapp-agent/whatsapp_agent_platform.json`, with directory mode `0700` and file mode `0600` where POSIX permissions are supported.
- Status endpoints do not return the API key. Keep keys out of issue reports, screenshots, source control, and logs.
- These conversations are **not end-to-end encrypted**. Do not send passwords, API keys, financial credentials, or other sensitive information.
- The integration is text-only. Media, groups, multi-agent routing, and automatic key rotation are not implemented in V1.
- Meta's endpoint contract, account eligibility, limits, and privacy terms must be confirmed for the account in use.

## 4. Troubleshooting

- **401:** Meta rejected the API key; re-enter it in the UI.
- **403:** Meta refused the operation or the sender/recipient is not eligible.
- **429:** rate limit reached; NOVA backs off before retrying.
- **Model ID unavailable:** inspect the local model listing and set `NOVA_WHATSAPP_AGENT_MODEL_ID` to the exact advertised Gemma ID.
- **Messages ignored:** verify that the configured creator ID exactly matches the sender ID documented by Meta.
- **Poller disconnected:** read the sanitized UI error and local service logs. Do not publish logs containing credentials.

## 5. Limitations

Automated tests use mocked HTTP and do not contact Meta or load model weights. A real account connectivity test, target-machine inference test, and verification of Meta's current API contract are still required. The implementation does not claim those external checks have passed.
