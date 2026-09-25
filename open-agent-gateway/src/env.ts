/**
 * Worker environment bindings for open-agent-gateway.
 * Base bindings/vars come from `wrangler types` (Cloudflare.Env).
 * Secrets via `wrangler secret put` — declared here until added to wrangler.
 */

export type Env = Cloudflare.Env & {
  APMIX_API_KEY?: string;
  APMIX_BASE_URL?: string;
  OPENAI_API_KEY?: string;
  OPENAI_BASE_URL?: string;
  ANTHROPIC_API_KEY?: string;
  ANTHROPIC_BASE_URL?: string;
  CUSTOM_BASE_URL?: string;
  CUSTOM_API_KEY?: string;
  ADMIN_TOKEN?: string;
  UPSTREAM_API_KEY?: string;
  UPSTREAM_BASE_URL?: string;
};
