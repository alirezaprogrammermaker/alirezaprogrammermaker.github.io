/**
 * open-agent-gateway — Cloudflare Workers multi-provider AI Agent gateway
 *
 * Slice ownership (see repo-internal fanout NOTES):
 *   w01 scaffold (this file) | w02 openai/apmix | w03 anthropic/custom
 *   w04 auth/keys | w05 chat route | w06 agent | w07 admin
 *   w08 examples | w09 tests/security | w10 deploy docs
 */

import { routeAgentRequest } from "agents";
import type { Env } from "./env";
import { GatewayAgent } from "./agent/gateway-agent";
import { handleHealth } from "./routes/health";
import { handleChatCompletions } from "./routes/chat";
import { handleAdmin } from "./routes/admin";
import { jsonError } from "./auth/middleware";

export { GatewayAgent };

function corsHeaders(): HeadersInit {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
  };
}

function withCors(res: Response): Response {
  const headers = new Headers(res.headers);
  for (const [k, v] of Object.entries(corsHeaders())) {
    headers.set(k, v);
  }
  return new Response(res.body, {
    status: res.status,
    statusText: res.statusText,
    headers,
  });
}

export default {
  async fetch(request: Request, env: Env, _ctx: ExecutionContext): Promise<Response> {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }

    const url = new URL(request.url);

    // Agent WebSocket / HTTP: /agents/gateway-agent/:instance
    const agentRes = await routeAgentRequest(request, env);
    if (agentRes) return withCors(agentRes);

    try {
      if (url.pathname === "/health" || url.pathname === "/") {
        return withCors(handleHealth());
      }

      if (url.pathname === "/v1/chat/completions") {
        return withCors(await handleChatCompletions(request, env));
      }

      if (url.pathname.startsWith("/admin")) {
        return withCors(await handleAdmin(request, env, url.pathname));
      }

      // // SLOT w08: OpenAPI-ish route map at /v1 or /openapi.json
      if (url.pathname === "/v1" || url.pathname === "/openapi.json") {
        return withCors(
          Response.json({
            service: "open-agent-gateway",
            routes: {
              "GET /health": "Liveness",
              "POST /v1/chat/completions": "OpenAI-compatible chat (SLOT w05)",
              "GET /admin/providers": "List providers (admin)",
              "POST /admin/keys": "Issue API key (SLOT w04/w07)",
              "DELETE /admin/keys/:id": "Revoke API key (SLOT w04/w07)",
              "WS /agents/gateway-agent/:name": "Agents SDK session (SLOT w06)",
            },
          }),
        );
      }

      return withCors(jsonError(404, "Not found", "not_found"));
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return withCors(jsonError(500, msg, "internal_error"));
    }
  },
} satisfies ExportedHandler<Env>;
