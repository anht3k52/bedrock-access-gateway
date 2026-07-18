# Public Bedrock Proxy (api.mrdev.cyou)

Expose this gateway publicly with **Cloudflare Tunnel** while the app binds only to `127.0.0.1:8000`.

## Architecture

```
Client (OpenAI SDK / Anthropic SDK / Claude Code)
  -> https://api.mrdev.cyou/api/v1/...  or  /v1/messages
    -> Cloudflare Tunnel
    -> http://127.0.0.1:8000 (uvicorn)
    -> Amazon Bedrock
```

## 1. Rotate AWS credentials

If an access key was pasted into chat, **deactivate/rotate it in IAM immediately**.

Preferred local setup (shared credentials file):

```powershell
aws configure
# AWS Access Key ID / Secret / region us-west-2
```

Do **not** put AWS secrets into git, `deploy/.env.local` committed files, or chat.

Minimum IAM permissions: Bedrock invoke / list foundation models (and inference profiles if used).

## 2. Configure gateway env

```powershell
cd C:\Users\admin\Documents\GitHub\bedrock-access-gateway
copy deploy\env.example deploy\.env.local
# Edit deploy\.env.local — set a long random ADMIN_API_KEY
# Optionally keep API_KEY as a temporary legacy shared key
```

Generate an admin key:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Start locally:

```powershell
.\deploy\run-gateway.ps1
```

Health:

```powershell
curl http://127.0.0.1:8000/health
```

## 3. Per-user API keys (admin API)

All admin routes require `Authorization: Bearer <ADMIN_API_KEY>`.

Create a key:

```powershell
curl http://127.0.0.1:8000/admin/keys `
  -H "Authorization: Bearer $env:ADMIN_API_KEY" `
  -H "Content-Type: application/json" `
  -d '{"name":"alice","rpm_limit":60,"monthly_token_quota":2000000}'
```

Response includes `api_key` **once** (`bag_<id>_<secret>`). Store it securely.

List / get usage / update quota / revoke:

- `GET /admin/keys`
- `GET /admin/keys/{key_id}`
- `PATCH /admin/keys/{key_id}` body `{"rpm_limit":30,"monthly_token_quota":500000}`
- `DELETE /admin/keys/{key_id}`

Defaults: **60 requests/minute**, **2,000,000 tokens/month**. Set `monthly_token_quota` to `0` for unlimited tokens. Exceeding RPM or monthly tokens returns HTTP `429`.

## 4. Cloudflare Tunnel + domain

```powershell
# Install cloudflared (winget or download from Cloudflare)
winget install --id Cloudflare.cloudflared -e

cloudflared tunnel login
cloudflared tunnel create bedrock-proxy
cloudflared tunnel route dns bedrock-proxy api.mrdev.cyou
```

Copy `deploy/cloudflared-config.example.yml` → `deploy/cloudflared-config.yml`, fill:

- `tunnel:` UUID
- `credentials-file:` path to `~/.cloudflared/<uuid>.json`

Run tunnel:

```powershell
cloudflared tunnel --config deploy\cloudflared-config.yml run
```

Cloudflare dashboard recommendations for `api.mrdev.cyou`:

- SSL/TLS mode: **Full**
- Always Use HTTPS: On
- Caching: bypass `/api/*` (API traffic)
- Optional WAF + rate limiting rules as a second layer

Register auto-start tasks (optional):

```powershell
.\deploy\install-windows-tasks.ps1
```

## 5. Client usage

### OpenAI-compatible (Chat Completions)

```text
base_url = https://api.mrdev.cyou/api/v1
api_key  = bag_xxxxxxxx_...
model    = claude-opus-4-6
```

```python
from openai import OpenAI

client = OpenAI(
    api_key="bag_...",
    base_url="https://api.mrdev.cyou/api/v1",
)
print(client.models.list())
```

### Anthropic Messages (`/v1/messages`)

Native Anthropic path for Claude Code / anthropic SDK (no CCR required):

```text
ANTHROPIC_BASE_URL = https://api.mrdev.cyou
ANTHROPIC_API_KEY  = bag_xxxxxxxx_...
# POST https://api.mrdev.cyou/v1/messages
# also: POST https://api.mrdev.cyou/api/v1/messages
```

Auth: `x-api-key: bag_...` **or** `Authorization: Bearer bag_...`.
Use short model IDs (`claude-opus-4-6`), not `us.anthropic.*`.

```powershell
$env:ANTHROPIC_BASE_URL = "https://api.mrdev.cyou"
$env:ANTHROPIC_API_KEY = "bag_xxxxxxxx"
claude
```

```bash
curl https://api.mrdev.cyou/v1/messages \
  -H "x-api-key: bag_xxxxxxxx" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-opus-4-6","max_tokens":256,"messages":[{"role":"user","content":"hi"}]}'
```

## 6. Web portal (User + Admin)

Gateway serves a portal at `/`:

- **Docs** (`/#/docs`): Apidog-style docs — IDE guides, **Messages API**, Chat Completions, models
- **Admin** (`/#/admin/login`): dashboard for **CDK** + API keys + model tiers
- **User** (`/#/user`): redeem CDK → API key (once) → Chat at `/#/chat`

Local: `http://127.0.0.1:8000/#/docs`
Public: `https://api.mrdev.cyou/#/docs`

API:
- `POST /admin/login` — username/password → session token
- `POST /admin/cdks` — tạo CDK
- `POST /api/v1/redeem` — user đổi CDK lấy key
- `GET /api/v1/me` — xem usage (không trừ RPM)
- `POST /v1/messages` — Anthropic Messages (cũng `/api/v1/messages`)
- `POST /api/v1/chat/completions` — OpenAI Chat Completions
- `POST /api/v1/responses` — OpenAI Responses shim


## 7. Operational notes

- The Windows machine must stay online.
- SQLite is for a **single** uvicorn process. Do not scale to multiple workers without moving quota state to Postgres/Redis.
- Legacy `API_KEY` remains usable while `ENABLE_LEGACY_API_KEY=true`; prefer issuing per-user keys and then disabling legacy access.
