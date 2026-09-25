/**
 * OpenAI-style error helpers for the chat completions gateway.
 */

import type { OpenAIErrorBody, OpenAIErrorType } from "./types";

export function openAIError(
  status: number,
  message: string,
  type: OpenAIErrorType,
  opts?: { param?: string | null; code?: string | null; headers?: HeadersInit },
): Response {
  const body: OpenAIErrorBody = {
    error: {
      message,
      type,
      param: opts?.param ?? null,
      code: opts?.code ?? null,
    },
  };
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      ...(opts?.headers ?? {}),
    },
  });
}

export function methodNotAllowed(allow = "POST"): Response {
  return openAIError(405, `Method not allowed. Use ${allow}.`, "invalid_request_error", {
    code: "method_not_allowed",
    headers: { Allow: allow },
  });
}

export function unauthorized(message = "Missing or invalid Authorization Bearer token."): Response {
  return openAIError(401, message, "authentication_error", {
    code: "invalid_api_key",
  });
}

export function badRequest(message: string, param?: string | null, code?: string): Response {
  return openAIError(400, message, "invalid_request_error", {
    param: param ?? null,
    code: code ?? "invalid_request",
  });
}

export function rateLimited(message = "Rate limit exceeded."): Response {
  return openAIError(429, message, "rate_limit_error", {
    code: "rate_limit_exceeded",
  });
}

export function serverError(message = "Internal server error."): Response {
  return openAIError(500, message, "server_error", {
    code: "internal_error",
  });
}

export function upstreamError(status: number, message: string): Response {
  const type: OpenAIErrorType =
    status === 401 || status === 403
      ? "authentication_error"
      : status === 429
        ? "rate_limit_error"
        : status >= 500
          ? "server_error"
          : "api_error";
  return openAIError(status >= 400 && status < 600 ? status : 502, message, type, {
    code: "upstream_error",
  });
}
