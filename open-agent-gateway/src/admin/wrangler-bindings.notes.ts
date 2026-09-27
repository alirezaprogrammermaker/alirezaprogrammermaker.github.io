/**
 * Minimal wrangler bindings expected by w07 admin routes.
 * Merge into root wrangler.toml / wrangler.jsonc (w01/w10).
 *
 * [[kv_namespaces]]
 * binding = "API_KEYS"
 * id = "<kv_namespace_id>"
 *
 * [vars]
 * # PROVIDER_REGISTRY = '[{"id":"apmix","name":"apmix","kind":"openai-compatible","adapter":"openai-compatible","enabled":true,"baseUrlHint":"https://api.apmix.ai/v1","models":["gpt-6-luna-free"]}]'
 * # ADMIN_CORS_ORIGIN = "https://ops.example.com"
 *
 * Secrets (wrangler secret put):
 *   ADMIN_TOKEN
 */
export {};
