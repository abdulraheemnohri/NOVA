# WhatsApp Cloud API third-party agent bridge

## Important distinction
This is NOVA's optional **WhatsApp Business Platform / Cloud API webhook bridge**. It does not enable or emulate Meta's limited consumer WhatsApp app agent-linking experience. Availability, account eligibility, message templates and platform policies are controlled by Meta.

## 1. Meta setup
1. Create/configure a Meta developer app and WhatsApp Business Platform phone number.
2. Deploy NOVA behind a trusted HTTPS reverse proxy with a public callback URL. Do not expose the local FastAPI port directly to the internet.
3. In the Meta webhook configuration, use `https://YOUR_HOST/api/whatsapp/webhook`, subscribe to WhatsApp message events, and configure the same verification token as `NOVA_WHATSAPP_VERIFY_TOKEN`.
4. Set `NOVA_WHATSAPP_APP_SECRET`, `NOVA_WHATSAPP_ACCESS_TOKEN`, and `NOVA_WHATSAPP_PHONE_NUMBER_ID` in the backend environment. Keep these values out of source control and logs.
5. Set `NOVA_WHATSAPP_ALLOWED_SENDERS` to comma-separated, digits-only international sender numbers. An empty allowlist blocks every sender.

## 2. Connect third-party agents
1. In NOVA's **WhatsApp Agents** page, add up to five HTTPS endpoints. Each endpoint must accept JSON containing `message`, `channel`, `sender`, `agent`, and `message_id`, with a bearer token.
2. Configure the matching token environment variable (for example, `NOVA_WHATSAPP_AGENT_PRIMARY_TOKEN`) in the backend environment. NOVA stores the variable name, not the secret value.
3. Enable only providers you trust. Endpoint redirects are rejected, HTTPS is required, and private/non-public IP addresses are blocked at dispatch.
4. When more than one agent is enabled, message `/agent <slug> your message`. If exactly one agent is enabled, plain text is sent to it. Only text messages are forwarded; attachments are ignored.
5. Configure the provider response as JSON with a non-empty `reply` string. NOVA sends that text back through the configured WhatsApp Cloud API phone number.

## 3. Privacy and security
- The webhook verifies Meta's `X-Hub-Signature-256` HMAC using the app secret and verifies the subscription challenge using the verification token.
- Only configured sender numbers are forwarded. Do not add shared or group numbers to the allowlist.
- The remote agent receives the message text, sender number, selected agent slug, and message ID. Do not send secrets or sensitive personal information.
- **WhatsApp does not consider these third-party agent conversations end-to-end encrypted.** Meta and the configured agent service process messages.
- NOVA does not store agent bearer-token values in SQLite or expose them in the UI. Keep environment files readable only by the service operator.
- The public webhook is exempt from NOVA's local bearer-token middleware only because Meta cannot send that token; HMAC signature verification is mandatory.
- Use HTTPS, a firewall/reverse proxy, rate limits, monitoring, and an up-to-date Meta Graph API version in production.

## Environment variables
See `.env.example` for the complete optional variable list. Do not commit populated credentials.
