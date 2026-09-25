/**
 * open-agent-gateway — Cloudflare Workers multi-provider AI Agent gateway
 *
 * Integrated slices:
 *   w01 scaffold | w02 providers | w03 anthropic-style | w05 gateway | w07 admin
 * Remaining: w04 auth store polish | w06 agent tools | w08 examples | w09 tests | w10 deploy
 */

import { routeAgentRequest } from "agents";
import type { Env } from "./env";
import { GatewayAgent } from "./agent/gateway-agent";
import { handleHealth } from "./routes/health";
import {
  handleChatCompletions,
  isChatCompletionsPath,
  type GatewayEnv,
} from "./gateway";
import { handleAdminRequest, type AdminEnv } from "./admin";
import { createProvidersFromEnv } from "./providers/registry";
import { createW03Providers } from "./providers/anthropic-style/registry";
import { createUpstreamOpenAIAdapter } from "./gateway/upstream";
import type { ProviderAdapter } from "./gateway/types";
import { APMIX_DEFAULT_BASE_URL, APMIX_DEFAULT_MODEL } from "./providers/apmix";

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

function asGatewayEnv(env: Env): GatewayEnv {
  return {
    API_KEYS: env.API_KEYS,
    UPSTREAM_API_KEY: env.UPSTREAM_API_KEY ?? env.APMIX_API_KEY,
    UPSTREAM_BASE_URL:
      env.UPSTREAM_BASE_URL ?? env.APMIX_BASE_URL ?? APMIX_DEFAULT_BASE_URL,
    DEFAULT_MODEL: env.GATEWAY_DEFAULT_MODEL || APMIX_DEFAULT_MODEL,
  };
}

function asAdminEnv(env: Env): AdminEnv | null {
  if (!env.ADMIN_TOKEN) return null;
  return {
    ADMIN_TOKEN: env.ADMIN_TOKEN,
    API_KEYS: env.API_KEYS,
    ADMIN_CORS_ORIGIN: "*",
    PROVIDER_REGISTRY: undefined,
  };
}

/** Prefer registered apmix/openai provider; fall back to upstream adapter. */
function resolveChatAdapter(env: Env): ProviderAdapter {
  const registry = createProvidersFromEnv(env);
  const defaultId = env.GATEWAY_DEFAULT_PROVIDER || "apmix";
  if (registry.has(defaultId)) {
    const p = registry.get(defaultId);
    return {
      async complete(params) {
        const result = await p.complete({
          model: params.model,
          messages: params.messages as never,
          stream: false,
          signal: params.signal,
          extras: params.extras,
        });
        if (result instanceof ReadableStream) {
          throw new Error("Unexpected stream from non-stream complete()");
        }
        return {
          id: result.id,
          model: result.model,
          created: result.created,
          message: result.message,
          finish_reason: result.finish_reason,
          usage: result.usage,
        };
      },
      async completeStream(params) {
        return p.completeStream({
          model: params.model,
          messages: params.messages as never,
          stream: true,
          signal: params.signal,
          extras: params.extras,
        });
      },
    };
  }
  return createUpstreamOpenAIAdapter(asGatewayEnv(env));
}

export default {
  async fetch(
    request: Request,
    env: Env,
    ctx: ExecutionContext,
  ): Promise<Response> {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }

    const url = new URL(request.url);

    // Agents SDK: /agents/gateway-agent/:instance — SLOT w06
    const agentRes = await routeAgentRequest(request, env);
    if (agentRes) return withCors(agentRes);

    try {
      if (url.pathname === "/health" || url.pathname === "/") {
        return withCors(handleHealth());
      }

      // w07 admin
      if (url.pathname.startsWith("/admin")) {
        const adminEnv = asAdminEnv(env);
        if (!adminEnv) {
          return withCors(
            Response.json(
              {
                error: {
                  code: "misconfigured",
                  message: "ADMIN_TOKEN secret is not configured",
                },
              },
              { status: 503 },
            ),
          );
        }
        const adminRes = await handleAdminRequest(request, adminEnv);
        if (adminRes) return withCors(adminRes);
      }

      // w05 chat completions
      if (isChatCompletionsPath(url.pathname)) {
        const adapter = resolveChatAdapter(env);
        return withCors(
          await handleChatCompletions(request, asGatewayEnv(env), ctx, {
            getAdapter: () => adapter,
          }),
        );
      }

      // Route map (w08 can expand OpenAPI)
      if (url.pathname === "/v1" || url.pathname === "/openapi.json") {
        const w02 = createProvidersFromEnv(env).list();
        const w03 = createW03Providers(env).map((p) => p.id);
        return withCors(
          Response.json({
            service: "open-agent-gateway",
            providers: { registered: w02, anthropic_style: w03 },
            routes: {
              "GET /health": "Liveness",
              "POST /v1/chat/completions": "OpenAI-compatible chat (w05)",
              "GET /admin/providers": "List providers (w07)",
              "POST /admin/keys": "Issue API key (w07)",
              "DELETE /admin/keys/:id": "Revoke API key (w07)",
              "WS /agents/gateway-agent/:name": "Agents SDK session (w06)",
            },
          }),
        );
      }

      return withCors(
        Response.json(
          { error: { message: "Not found", type: "invalid_request_error" } },
          { status: 404 },
        ),
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return withCors(
        Response.json(
          { error: { message: msg, type: "server_error" } },
          { status: 500 },
        ),
      );
    }
  },
} satisfies ExportedHandler<Env>;
