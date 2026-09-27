/**
 * POST /v1/chat/completions — OpenAI-compatible gateway handler (w05).
 *
 * Features:
 * - Bearer auth hook (w04 storage)
 * - Request validation / normalization
 * - Non-streaming JSON responses
 * - Streaming SSE (native upstream or synthesized fallback)
 * - AbortSignal on client disconnect
 * - OpenAI-shaped errors
 * - No secret logging
 */

import type {
  ChatCompletionResponse,
  GatewayAuthContext,
  GatewayEnv,
  ProviderAdapter,
} from "./types";
import {
  badRequest,
  methodNotAllowed,
  serverError,
  upstreamError,
} from "./errors";
import { requireAuth, safeAuthLog, type Authenticator } from "./auth";
import {
  normalizeChatCompletionRequest,
  newCompletionId,
  newRequestId,
  stripClientOnlyFields,
  wantsStream,
} from "./validate";
import { jsonHeaders, streamingHeaders, synthesizeSseFromText } from "./streaming";
import { createUpstreamOpenAIAdapter, UpstreamHttpError } from "./upstream";

export interface ChatCompletionsDeps {
  authenticate?: Authenticator;
  /** Inject provider resolver; default uses UPSTREAM_* env proxy */
  getAdapter?: (env: GatewayEnv, model: string) => ProviderAdapter;
  /** Optional rate-limit stub (w09) — return Response to block */
  rateLimit?: (
    request: Request,
    env: GatewayEnv,
    auth: GatewayAuthContext,
  ) => Promise<Response | null>;
}

function defaultGetAdapter(env: GatewayEnv, _model: string): ProviderAdapter {
  void _model;
  return createUpstreamOpenAIAdapter(env);
}

/**
 * Route entry: call from worker fetch() when pathname is /v1/chat/completions.
 */
export async function handleChatCompletions(
  request: Request,
  env: GatewayEnv,
  ctx: ExecutionContext,
  deps: ChatCompletionsDeps = {},
): Promise<Response> {
  const requestId = newRequestId();

  if (request.method !== "POST") {
    return methodNotAllowed("POST");
  }

  const authResult = await requireAuth(request, env, deps.authenticate);
  if (authResult instanceof Response) {
    // attach request id
    const headers = new Headers(authResult.headers);
    headers.set("x-request-id", requestId);
    return new Response(authResult.body, { status: authResult.status, headers });
  }
  const auth = authResult;

  if (deps.rateLimit) {
    const limited = await deps.rateLimit(request, env, auth);
    if (limited) {
      const headers = new Headers(limited.headers);
      headers.set("x-request-id", requestId);
      return new Response(limited.body, { status: limited.status, headers });
    }
  }

  let raw: unknown;
  try {
    raw = await request.json();
  } catch {
    return withRequestId(badRequest("Invalid JSON body", null, "invalid_json"), requestId);
  }

  const url = new URL(request.url);
  const validated = normalizeChatCompletionRequest(raw, {
    defaultModel: env.DEFAULT_MODEL,
  });
  if (!validated.ok) {
    return withRequestId(
      badRequest(validated.message, validated.param, validated.code),
      requestId,
    );
  }

  const body = validated.value;
  const stream = wantsStream(body, url);
  body.stream = stream;

  const adapter = (deps.getAdapter ?? defaultGetAdapter)(env, body.model);
  const extras = stripClientOnlyFields(body);
  delete extras.stream;
  delete extras.model;
  delete extras.messages;

  const signal = request.signal;

  // Safe structured log (no tokens)
  console.log(
    JSON.stringify({
      msg: "chat_completions",
      requestId,
      ...safeAuthLog(auth),
      model: body.model,
      stream,
      messageCount: body.messages.length,
    }),
  );

  try {
    if (stream) {
      return await handleStream({
        adapter,
        body,
        extras,
        signal,
        requestId,
        ctx,
      });
    }
    return await handleOnce({
      adapter,
      body,
      extras,
      signal,
      requestId,
    });
  } catch (err) {
    if (err instanceof UpstreamHttpError) {
      let message = `Upstream provider error (${err.status})`;
      try {
        const parsed = JSON.parse(err.bodyText) as { error?: { message?: string } };
        if (parsed?.error?.message) message = parsed.error.message;
      } catch {
        if (err.bodyText && err.bodyText.length < 200) message = err.bodyText;
      }
      return withRequestId(upstreamError(err.status, message), requestId);
    }
    if ((err as Error)?.name === "AbortError") {
      return withRequestId(serverError("Request aborted"), requestId);
    }
    console.error(
      JSON.stringify({
        msg: "chat_completions_error",
        requestId,
        error: (err as Error)?.message ?? "unknown",
      }),
    );
    return withRequestId(serverError(), requestId);
  }
}

async function handleOnce(opts: {
  adapter: ProviderAdapter;
  body: import("./types").ChatCompletionRequest;
  extras: Record<string, unknown>;
  signal: AbortSignal;
  requestId: string;
}): Promise<Response> {
  const result = await opts.adapter.complete({
    model: opts.body.model,
    messages: opts.body.messages,
    stream: false,
    signal: opts.signal,
    extras: opts.extras,
  });

  const response: ChatCompletionResponse = {
    id: result.id || newCompletionId(),
    object: "chat.completion",
    created: result.created || Math.floor(Date.now() / 1000),
    model: result.model || opts.body.model,
    choices: [
      {
        index: 0,
        message: {
          role: "assistant",
          content: result.message.content,
          tool_calls: result.message.tool_calls,
        },
        finish_reason: result.finish_reason,
      },
    ],
    usage: result.usage,
  };

  return new Response(JSON.stringify(response), {
    status: 200,
    headers: jsonHeaders(opts.requestId),
  });
}

async function handleStream(opts: {
  adapter: ProviderAdapter;
  body: import("./types").ChatCompletionRequest;
  extras: Record<string, unknown>;
  signal: AbortSignal;
  requestId: string;
  ctx: ExecutionContext;
}): Promise<Response> {
  const params = {
    model: opts.body.model,
    messages: opts.body.messages,
    stream: true as const,
    signal: opts.signal,
    extras: opts.extras,
  };

  let readable: ReadableStream<Uint8Array>;

  if (opts.adapter.completeStream) {
    readable = await opts.adapter.completeStream(params);
  } else {
    // Fallback: complete once, synthesize SSE (keeps OpenAI client compatibility)
    const result = await opts.adapter.complete({ ...params, stream: false });
    readable = synthesizeSseFromText({
      id: result.id || newCompletionId(),
      model: result.model || opts.body.model,
      created: result.created || Math.floor(Date.now() / 1000),
      content: result.message.content ?? "",
      finish_reason: result.finish_reason,
      usage: result.usage,
    });
  }

  // Ensure cancellation propagates
  const stream = readable;
  opts.ctx.waitUntil(
    (async () => {
      if (!opts.signal.aborted) return;
      try {
        await stream.cancel("client disconnected");
      } catch {
        /* ignore */
      }
    })(),
  );

  return new Response(stream, {
    status: 200,
    headers: streamingHeaders(opts.requestId),
  });
}

function withRequestId(res: Response, requestId: string): Response {
  const headers = new Headers(res.headers);
  headers.set("x-request-id", requestId);
  return new Response(res.body, { status: res.status, headers });
}

/** Path matcher helper for worker routers. */
export function isChatCompletionsPath(pathname: string): boolean {
  return (
    pathname === "/v1/chat/completions" ||
    pathname === "/chat/completions" // convenience alias
  );
}
