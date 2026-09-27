/**
 * Example worker fetch wiring for w01 integration.
 * Copy the switch branch into open-agent-gateway/src/index.ts.
 */

import {
  handleChatCompletions,
  isChatCompletionsPath,
  type GatewayEnv,
} from "../src/gateway";

export default {
  async fetch(request: Request, env: GatewayEnv, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    // CORS preflight (optional — useful for browser clients / examples)
    if (request.method === "OPTIONS" && isChatCompletionsPath(url.pathname)) {
      return new Response(null, {
        status: 204,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "POST, OPTIONS",
          "access-control-allow-headers": "Authorization, Content-Type",
          "access-control-max-age": "86400",
        },
      });
    }

    if (isChatCompletionsPath(url.pathname)) {
      const res = await handleChatCompletions(request, env, ctx);
      // Attach permissive CORS for examples; tighten in production (w10)
      const headers = new Headers(res.headers);
      headers.set("access-control-allow-origin", "*");
      return new Response(res.body, { status: res.status, headers });
    }

    return new Response(JSON.stringify({ error: { message: "Not found", type: "invalid_request_error" } }), {
      status: 404,
      headers: { "content-type": "application/json" },
    });
  },
};

/** Suggested wrangler bindings for this slice */
export const WRANGLER_BINDINGS_HINT = `
[vars]
UPSTREAM_BASE_URL = "https://api.apmix.ai/v1"
DEFAULT_MODEL = "gpt-6-luna-free"

# secrets: wrangler secret put UPSTREAM_API_KEY
# kv_namespaces: API_KEYS = { id = "..." }  # w04
`;
