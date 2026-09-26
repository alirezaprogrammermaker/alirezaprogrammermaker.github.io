# w06 → w01 integration

1. Copy `src/agent/*` over the stub `gateway-agent.ts`.
2. Keep `export { GatewayAgent }` and `routeAgentRequest` in `src/index.ts` (already scaffolded).
3. Wrangler binding/migration class name must stay `GatewayAgent` + `new_sqlite_classes`.
4. Secrets: `APMIX_API_KEY` or `UPSTREAM_API_KEY` (never commit).
