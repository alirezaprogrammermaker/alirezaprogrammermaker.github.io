/**
 * Request validation / normalization for POST /v1/chat/completions.
 */

import type { ChatCompletionRequest, ChatMessage } from "./types";

export type ValidateOk = { ok: true; value: ChatCompletionRequest };
export type ValidateErr = {
  ok: false;
  message: string;
  param?: string;
  code?: string;
};
export type ValidateResult = ValidateOk | ValidateErr;

const FORWARD_KEYS = [
  "temperature",
  "top_p",
  "n",
  "max_tokens",
  "max_completion_tokens",
  "stop",
  "presence_penalty",
  "frequency_penalty",
  "user",
  "seed",
  "tools",
  "tool_choice",
  "response_format",
  "stream_options",
  "logit_bias",
  "logprobs",
  "top_logprobs",
  "parallel_tool_calls",
] as const;

export function wantsStream(body: { stream?: boolean }, url: URL): boolean {
  if (typeof body.stream === "boolean") return body.stream;
  const q = url.searchParams.get("stream");
  if (q === "true" || q === "1") return true;
  if (q === "false" || q === "0") return false;
  return false;
}

export function normalizeChatCompletionRequest(
  raw: unknown,
  opts?: { defaultModel?: string },
): ValidateResult {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    return { ok: false, message: "Request body must be a JSON object.", code: "invalid_json_body" };
  }
  const body = raw as Record<string, unknown>;

  let model = typeof body.model === "string" ? body.model.trim() : "";
  if (!model && opts?.defaultModel) model = opts.defaultModel;
  if (!model) {
    return {
      ok: false,
      message: "Missing required parameter: model",
      param: "model",
      code: "missing_required_parameter",
    };
  }

  if (!Array.isArray(body.messages)) {
    return {
      ok: false,
      message: "Missing required parameter: messages",
      param: "messages",
      code: "missing_required_parameter",
    };
  }
  if (body.messages.length === 0) {
    return {
      ok: false,
      message: "messages must be a non-empty array",
      param: "messages",
      code: "invalid_messages",
    };
  }

  for (let i = 0; i < body.messages.length; i++) {
    const m = body.messages[i] as ChatMessage;
    if (!m || typeof m !== "object") {
      return {
        ok: false,
        message: `messages[${i}] must be an object`,
        param: "messages",
        code: "invalid_messages",
      };
    }
    if (typeof m.role !== "string" || !m.role) {
      return {
        ok: false,
        message: `messages[${i}].role is required`,
        param: "messages",
        code: "invalid_messages",
      };
    }
  }

  if (body.stream !== undefined && typeof body.stream !== "boolean") {
    return {
      ok: false,
      message: "stream must be a boolean",
      param: "stream",
      code: "invalid_parameter",
    };
  }

  if (body.n !== undefined) {
    if (typeof body.n !== "number" || !Number.isInteger(body.n) || body.n < 1) {
      return {
        ok: false,
        message: "n must be a positive integer",
        param: "n",
        code: "invalid_parameter",
      };
    }
    // v1 gateway: only n=1 for streaming path stability
    if (body.stream === true && body.n !== 1) {
      return {
        ok: false,
        message: "streaming with n > 1 is not supported",
        param: "n",
        code: "unsupported_parameter",
      };
    }
  }

  const out: ChatCompletionRequest = {
    model,
    messages: body.messages as ChatMessage[],
    stream: body.stream === true,
  };

  for (const k of FORWARD_KEYS) {
    if (k in body && body[k] !== undefined) {
      (out as Record<string, unknown>)[k] = body[k];
    }
  }

  return { ok: true, value: out };
}

/** Strip client-only / sensitive fields before upstream forward. */
export function stripClientOnlyFields(
  body: ChatCompletionRequest,
): Record<string, unknown> {
  const {
    // never forward gateway auth artifacts if somehow present
    api_key: _a,
    authorization: _b,
    ...rest
  } = body as ChatCompletionRequest & { api_key?: unknown; authorization?: unknown };
  void _a;
  void _b;
  return { ...rest };
}

export function newCompletionId(): string {
  const rand = crypto.randomUUID().replace(/-/g, "").slice(0, 24);
  return `chatcmpl-${rand}`;
}

export function newRequestId(): string {
  return `req_${crypto.randomUUID().replace(/-/g, "")}`;
}
