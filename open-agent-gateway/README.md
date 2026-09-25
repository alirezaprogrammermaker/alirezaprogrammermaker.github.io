# open-agent-gateway

Cloudflare Workers multi-provider AI Agent gateway: OpenAI-compatible HTTP (`/v1/chat/completions`), issued API keys, pluggable providers (apmix, OpenAI, Anthropic, custom base URL), and an Agents SDK Durable Object for stateful WebSocket sessions.

> Lives in `open-agent-gateway/` so the github.io site root stays untouched.

## Quickstart

```bash
cd open-agent-gateway
npm install
cp .env.example .dev.vars   # fill secrets locally (never commit)
npx wrangler kv namespace create API_KEYS
# paste the id into wrangler.jsonc kv_namespaces
npx wrangler secret put APMIX_API_KEY
npx wrangler secret put ADMIN_TOKEN
npm run dev
```

```bash
curl -s http://localhost:8787/health
curl -s http://localhost:8787/v1 \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Bootstrap chat (ADMIN_TOKEN until key issuance lands — SLOT w04)
curl -s http://localhost:8787/v1/chat/completions \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-6-luna-free","messages":[{"role":"user","content":"hi"}]}'
```

## Source layout (slice slots)

| Path | Owner | Role |
|------|-------|------|
| `src/index.ts`, `wrangler.jsonc`, `package.json`, `README.md` | **w01** | Scaffold + integration |
| `src/providers/openai.ts`, `apmix.ts`, `types.ts`, `registry.ts` | **w02** | OpenAI-compatible + apmix |
| `src/providers/anthropic.ts`, `custom.ts` | **w03** | Anthropic + custom baseURL |
| `src/auth/keys.ts`, `middleware.ts` | **w04** | Key hash/KV + Bearer auth |
| `src/routes/chat.ts` | **w05** | `/v1/chat/completions` + stream |
| `src/agent/gateway-agent.ts` | **w06** | Agents SDK class + tools |
| `src/routes/admin.ts` | **w07** | Create/revoke keys, list providers |
| `examples/` | **w08** | curl + TS client + route map |
| `tests/`, `src/middleware/rate-limit.ts` | **w09** | Vitest, hardening, rate limits |
| `docs/deploy.md` | **w10** | Production deploy recipes |

Search the tree for `SLOT wNN` comments.

## Providers

`ProviderAdapter.complete({ model, messages, stream? })` — see `src/providers/types.ts`.

| Id | Base | Status |
|----|------|--------|
| `apmix` | `https://api.apmix.ai/v1` | Minimal working stub (w02 to harden) |
| `openai` | OpenAI | SLOT w02 |
| `anthropic` | Anthropic Messages | SLOT w03 |
| `custom` | `CUSTOM_BASE_URL` | SLOT w03 |

Default provider/model: wrangler `vars` `GATEWAY_DEFAULT_PROVIDER` / `GATEWAY_DEFAULT_MODEL`.

## Auth

- Client apps: `Authorization: Bearer <issued_api_key>`
- Keys stored as **SHA-256 hashes** in KV (`API_KEYS`) — SLOT w04
- Admin: `ADMIN_TOKEN` secret for `/admin/*`
- Until w04 ships, `ADMIN_TOKEN` also bootstraps `/v1/chat/completions`

## Agents

WebSocket / HTTP via Agents SDK:

` /agents/gateway-agent/<session-id> `

Class: `GatewayAgent` (SQLite-backed Durable Object). SLOT w06 wires tools + provider calls.

## Scripts

| Script | Command |
|--------|---------|
| Dev | `npm run dev` |
| Deploy | `npm run deploy` |
| Types | `npm run types` |
| Test | `npm run test` |

## Env / secrets

See `.env.example`. Prefer `wrangler secret put` for production.

## License

Same as parent repository.
