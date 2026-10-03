# Qwen Workflow API (Cloudflare Workers + D1)

OpenAI-shaped async control plane for the Qwen CLI browser worker.

## Features

- `POST /v1/chat/completions` — text (async job)
- `POST /v1/images/generations` — image
- `POST /v1/videos/generations` — video
- `POST /v1/accounts` — register Qwen email/password for the worker pool
- Continuity: responses include `chat_id` + `account_id`; send `chat_id` later to continue on the **same** Qwen account/chat
- Worker endpoints: `/v1/worker/claim`, `/v1/worker/jobs/{id}/complete`
- Daily cron: purge messages/jobs/chats older than 30 days (batched)

## Auth

| Key | Header | Use |
| --- | --- | --- |
| `API_KEY` | `Authorization: Bearer …` | Client apps |
| `WORKER_KEY` | `Authorization: Bearer …` | GHA poller only |
| `ACCOUNT_SECRET` | (secret) | Encrypt Qwen passwords at rest |

## Free-tier care

- Idle claim = **1 D1 read**, 0 writes
- Client should poll jobs every **5–10s**, not 1s
- Cleanup cron once daily (`0 3 * * *` UTC), batched deletes

## Deploy

```bash
export CLOUDFLARE_API_TOKEN=...
export CLOUDFLARE_ACCOUNT_ID=...
npm i
npx wrangler d1 create qwen_workflow
# put database_id into wrangler.jsonc
npx wrangler d1 migrations apply qwen_workflow --remote
npx wrangler secret put API_KEY
npx wrangler secret put WORKER_KEY
npx wrangler secret put ACCOUNT_SECRET
uv run pywrangler deploy
```
