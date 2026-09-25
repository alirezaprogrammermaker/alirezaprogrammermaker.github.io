/**
 * // SLOT w05 — OpenAI-compatible /v1/chat/completions (+ streaming)
 */

import type { Env } from "../env";
import { requireApiKey, jsonError } from "../auth/middleware";
import { resolveDefaultProvider, resolveProvider } from "../providers/registry";
import type { ChatMessage, ProviderId } from "../providers/types";

interface ChatBody {
  model?: string;
  messages?: ChatMessage[];
  stream?: boolean;
  temperature?: number;
  max_tokens?: number;
  provider?: ProviderId;
}

export async function handleChatCompletions(
  request: Request,
  env: Env,
): Promise<Response> {
  if (request.method !== "POST") {
    return jsonError(405, "Method not allowed", "method_not_allowed");
  }

  const authErr = await requireApiKey(request, env);
  if (authErr) return authErr;

  let body: ChatBody;
  try {
    body = (await request.json()) as ChatBody;
  } catch {
    return jsonError(400, "Invalid JSON body", "invalid_request");
  }

  if (!body.messages || !Array.isArray(body.messages) || body.messages.length === 0) {
    return jsonError(400, "`messages` is required", "invalid_request");
  }

  const model = body.model || env.GATEWAY_DEFAULT_MODEL || "gpt-6-luna-free";
  const provider = body.provider
    ? resolveProvider(body.provider, env)
    : resolveDefaultProvider(env);

  // SLOT w05: full OpenAI response shape + SSE streaming when body.stream
  if (body.stream) {
    return jsonError(
      501,
      "Streaming not implemented yet (SLOT w05)",
      "not_implemented",
    );
  }

  try {
    const result = await provider.complete({
      model,
      messages: body.messages,
      stream: false,
      temperature: body.temperature,
      max_tokens: body.max_tokens,
    });

    if (result instanceof ReadableStream) {
      return new Response(result, {
        headers: { "Content-Type": "text/event-stream" },
      });
    }

    const id = `chatcmpl_${crypto.randomUUID().replace(/-/g, "").slice(0, 24)}`;
    return Response.json({
      id,
      object: "chat.completion",
      created: Math.floor(Date.now() / 1000),
      model,
      choices: [
        {
          index: 0,
          message: { role: "assistant", content: result.content },
          finish_reason: result.finish_reason ?? "stop",
        },
      ],
      usage: result.usage ?? {
        prompt_tokens: 0,
        completion_tokens: 0,
        total_tokens: 0,
      },
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (msg.includes("SLOT")) {
      return jsonError(501, msg, "not_implemented");
    }
    return jsonError(502, msg, "upstream_error");
  }
}
