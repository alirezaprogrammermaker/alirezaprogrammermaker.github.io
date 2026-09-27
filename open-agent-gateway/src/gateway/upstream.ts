/**
 * Fallback OpenAI-compatible upstream proxy (used until w02 adapter is wired).
 * Speaks the same HTTP dialect as apmix / OpenAI.
 */

import type {
  CompleteParams,
  CompleteResult,
  GatewayEnv,
  ProviderAdapter,
} from "./types";
import { normalizeUpstreamSse } from "./streaming";
import { newCompletionId } from "./validate";

function joinUrl(base: string, path: string): string {
  const b = base.replace(/\/+$/, "");
  const p = path.startsWith("/") ? path : `/${path}`;
  // If base already ends with /v1 and path starts with /v1, avoid double
  if (b.endsWith("/v1") && p.startsWith("/v1/")) {
    return b + p.slice(3);
  }
  return b + p;
}

export function createUpstreamOpenAIAdapter(env: GatewayEnv): ProviderAdapter {
  const baseURL = (env.UPSTREAM_BASE_URL || "https://api.apmix.ai/v1").replace(/\/+$/, "");
  const apiKey = env.UPSTREAM_API_KEY || "";

  async function postChat(params: CompleteParams, stream: boolean): Promise<Response> {
    if (!apiKey) {
      throw new Error("UPSTREAM_API_KEY is not configured");
    }
    const extras = params.extras ?? {};
    const body = {
      ...extras,
      model: params.model,
      messages: params.messages,
      stream,
    };
    // Ensure stream flag wins over extras
    body.stream = stream;

    return fetch(joinUrl(baseURL, "/chat/completions"), {
      method: "POST",
      headers: {
        authorization: `Bearer ${apiKey}`,
        "content-type": "application/json",
        accept: stream ? "text/event-stream" : "application/json",
      },
      body: JSON.stringify(body),
      signal: params.signal,
    });
  }

  return {
    async complete(params: CompleteParams): Promise<CompleteResult> {
      const res = await postChat(params, false);
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new UpstreamHttpError(res.status, text || res.statusText);
      }
      const json = (await res.json()) as {
        id?: string;
        model?: string;
        created?: number;
        choices?: Array<{
          message?: { role?: string; content?: string | null; tool_calls?: unknown[] };
          finish_reason?: string | null;
        }>;
        usage?: CompleteResult["usage"];
      };
      const choice = json.choices?.[0];
      return {
        id: json.id || newCompletionId(),
        model: json.model || params.model,
        created: json.created || Math.floor(Date.now() / 1000),
        message: {
          role: "assistant",
          content: choice?.message?.content ?? null,
          tool_calls: choice?.message?.tool_calls,
        },
        finish_reason: choice?.finish_reason ?? "stop",
        usage: json.usage,
      };
    },

    async completeStream(params: CompleteParams): Promise<ReadableStream<Uint8Array>> {
      const res = await postChat(params, true);
      if (!res.ok || !res.body) {
        const text = await res.text().catch(() => "");
        throw new UpstreamHttpError(res.status, text || res.statusText);
      }
      return normalizeUpstreamSse(res.body, { signal: params.signal });
    },
  };
}

export class UpstreamHttpError extends Error {
  status: number;
  bodyText: string;
  constructor(status: number, bodyText: string) {
    super(`Upstream HTTP ${status}`);
    this.status = status;
    this.bodyText = bodyText;
  }
}
