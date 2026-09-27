# Deploying open-agent-gateway

> // SLOT w10 — expand with multi-provider recipes and production hardening

## Prerequisites

- Cloudflare account + Wrangler 4.x
- Node 18+
- KV namespace for hashed API keys

## Steps

1. `cd open-agent-gateway && npm install`
2. Create KV: `npx wrangler kv namespace create API_KEYS`
3. Paste `id` / `preview_id` into `wrangler.jsonc`
4. Set secrets:

```bash
npx wrangler secret put APMIX_API_KEY
npx wrangler secret put OPENAI_API_KEY      # optional
npx wrangler secret put ANTHROPIC_API_KEY   # optional
npx wrangler secret put ADMIN_TOKEN
npx wrangler secret put CUSTOM_API_KEY      # optional
```

5. Dry-run: `npm run deploy:dry`
6. Deploy: `npm run deploy`
7. Verify: `curl https://<worker>.workers.dev/health`

## Production notes

- Never commit `.dev.vars` or raw keys
- Rotate `ADMIN_TOKEN` after first key issuance works (SLOT w04)
- Enable observability in `wrangler.jsonc` (already on)
- Use `env.production` block for prod-specific vars

## Multi-provider recipes

- **apmix-only**: set `GATEWAY_DEFAULT_PROVIDER=apmix`, only `APMIX_API_KEY`
- **OpenAI fallback**: SLOT w02/w10 — document failover chain
- **Custom proxy**: set `CUSTOM_BASE_URL` + `CUSTOM_API_KEY` (SLOT w03)
