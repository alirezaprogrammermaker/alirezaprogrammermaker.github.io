/**
 * Generic custom baseURL provider.
 * Defaults to OpenAI-compatible POST {baseUrl}{path} chat completions.
 * Can also speak Anthropic-style when requestStyle === "anthropic".
 */

import {
  extractTextFromAnthropicContent,
  mapAnthropicUsage,
  mapOpenAIMessagesToAnthropic,
} from "./anthropic-map";
import { ProviderError, throwProviderHttpError } from "./errors";
import type {
  AuthHeaderMode,
  CompleteRequest,
  CompleteResponse,
  Provider,
  RequestStyle,
  TokenUsage,
} from "./types";

export interface CustomBaseURLProviderConfig {
  baseUrl: string;
  apiKey?: string;
  /** Path appended to baseUrl. Default: /v1/chat/completions */
  path?: string;
  headers?: Record<string, string>;
  authHeader?: AuthHeaderMode;
  requestStyle?: RequestStyle;
  defaultMaxTokens?: number;
  id?: string;
  fetch?: typeof fetch;
}

function joinUrl(baseUrl: string, path: string): string {
  const base = baseUrl.replace(/\/+$/, "");
  const p = path.startsWith("/") ? path : `/${path}`;
  // If base already ends with /v1 and path starts with /v1, avoid double
  if (base.endsWith("/v1") && p.startsWith("/v1/")) {
    return `${base}${p.slice(3)}`;
  }
  return `${base}${p}`;
}

function buildAuthHeaders(
  mode: AuthHeaderMode,
  apiKey: string | undefined,
): Record<string, string> {
  if (mode === "none" || !apiKey) return {};
  if (mode === "x-api-key") return { "x-api-key": apiKey };
  return { authorization: `Bearer ${apiKey}` };
}

function mapOpenAIUsage(usage: unknown): TokenUsage | undefined {
  if (!usage || typeof usage !== "object") return undefined;
  const u = usage as Record<string, number>;
  return {
    promptTokens: u.prompt_tokens,
    completionTokens: u.completion_tokens,
    totalTokens: u.total_tokens,
  };
}

export class CustomBaseURLProvider implements Provider {
  readonly id: string;
  private readonly baseUrl: string;
  private readonly path: string;
  private readonly apiKey?: string;
  private readonly headers: Record<string, string>;
  private readonly authHeader: AuthHeaderMode;
  private readonly requestStyle: RequestStyle;
  private readonly defaultMaxTokens: number;
  private readonly fetchImpl: typeof fetch;

  constructor(config: CustomBaseURLProviderConfig) {
    if (!config.baseUrl) {
      throw new ProviderError("Custom provider baseUrl required", {
        provider: config.id ?? "custom",
        code: "missing_base_url",
      });
    }
    // Basic SSRF guard: require http(s)
    if (!/^https?:\/\//i.test(config.baseUrl)) {
      throw new ProviderError("baseUrl must be http(s)", {
        provider: config.id ?? "custom",
        code: "invalid_base_url",
      });
    }
    this.id = config.id ?? "custom";
    this.baseUrl = config.baseUrl;
    this.path =
      config.path ??
      (config.requestStyle === "anthropic"
        ? "/v1/messages"
        : "/v1/chat/completions");
    this.apiKey = config.apiKey;
    this.headers = { ...(config.headers ?? {}) };
    this.authHeader =
      config.authHeader ??
      (config.requestStyle === "anthropic" ? "x-api-key" : "bearer");
    this.requestStyle = config.requestStyle ?? "openai";
    this.defaultMaxTokens = config.defaultMaxTokens ?? 1024;
    this.fetchImpl = config.fetch ?? fetch.bind(globalThis);
  }

  async complete(request: CompleteRequest): Promise<CompleteResponse> {
    if (this.requestStyle === "anthropic") {
      return this.completeAnthropicStyle(request);
    }
    return this.completeOpenAIStyle(request);
  }

  private async completeOpenAIStyle(
    request: CompleteRequest,
  ): Promise<CompleteResponse> {
    const url = joinUrl(this.baseUrl, this.path);
    const body: Record<string, unknown> = {
      model: request.model,
      messages: request.messages.map((m) => ({
        role: m.role,
        content: m.content,
        ...(m.name ? { name: m.name } : {}),
      })),
      ...(request.stream ? { stream: false } : {}),
      ...(request.max_tokens != null ? { max_tokens: request.max_tokens } : {}),
      ...(request.temperature != null
        ? { temperature: request.temperature }
        : {}),
      ...(request.top_p != null ? { top_p: request.top_p } : {}),
      ...(request.stop != null ? { stop: request.stop } : {}),
      ...(request.extra ?? {}),
    };

    const res = await this.fetchImpl(url, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...buildAuthHeaders(this.authHeader, this.apiKey),
        ...this.headers,
      },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      await throwProviderHttpError(this.id, res);
    }

    const raw = (await res.json()) as {
      choices?: Array<{
        message?: { content?: string };
        finish_reason?: string;
      }>;
      model?: string;
      usage?: unknown;
    };

    const content = raw.choices?.[0]?.message?.content ?? "";
    return {
      content: typeof content === "string" ? content : String(content ?? ""),
      model: raw.model ?? request.model,
      finishReason: raw.choices?.[0]?.finish_reason,
      usage: mapOpenAIUsage(raw.usage),
      raw,
    };
  }

  private async completeAnthropicStyle(
    request: CompleteRequest,
  ): Promise<CompleteResponse> {
    const { system, messages } = mapOpenAIMessagesToAnthropic(request.messages);
    const url = joinUrl(this.baseUrl, this.path);
    const body: Record<string, unknown> = {
      model: request.model,
      max_tokens: request.max_tokens ?? this.defaultMaxTokens,
      messages,
      ...(system ? { system } : {}),
      ...(request.temperature != null
        ? { temperature: request.temperature }
        : {}),
      ...(request.extra ?? {}),
    };

    const headers: Record<string, string> = {
      "content-type": "application/json",
      ...buildAuthHeaders(this.authHeader, this.apiKey),
      ...this.headers,
    };
    if (!headers["anthropic-version"]) {
      headers["anthropic-version"] = "2023-06-01";
    }

    const res = await this.fetchImpl(url, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      await throwProviderHttpError(this.id, res);
    }

    const raw = (await res.json()) as {
      content?: unknown;
      model?: string;
      stop_reason?: string;
      usage?: unknown;
    };

    return {
      content: extractTextFromAnthropicContent(raw.content),
      model: raw.model ?? request.model,
      finishReason: raw.stop_reason,
      usage: mapAnthropicUsage(raw.usage),
      raw,
    };
  }
}

export function createCustomBaseURLProvider(env: {
  CUSTOM_LLM_BASE_URL?: string;
  CUSTOM_LLM_API_KEY?: string;
  CUSTOM_LLM_PATH?: string;
  CUSTOM_LLM_AUTH?: string;
  CUSTOM_LLM_STYLE?: string;
  CUSTOM_LLM_EXTRA_HEADERS_JSON?: string;
}): CustomBaseURLProvider | null {
  if (!env.CUSTOM_LLM_BASE_URL) return null;

  let headers: Record<string, string> | undefined;
  if (env.CUSTOM_LLM_EXTRA_HEADERS_JSON) {
    try {
      headers = JSON.parse(env.CUSTOM_LLM_EXTRA_HEADERS_JSON) as Record<
        string,
        string
      >;
    } catch {
      throw new ProviderError("CUSTOM_LLM_EXTRA_HEADERS_JSON invalid JSON", {
        provider: "custom",
        code: "invalid_headers_json",
      });
    }
  }

  const auth = (env.CUSTOM_LLM_AUTH ?? "bearer") as AuthHeaderMode;
  const style = (env.CUSTOM_LLM_STYLE ?? "openai") as RequestStyle;

  return new CustomBaseURLProvider({
    baseUrl: env.CUSTOM_LLM_BASE_URL,
    apiKey: env.CUSTOM_LLM_API_KEY,
    path: env.CUSTOM_LLM_PATH,
    authHeader: auth,
    requestStyle: style,
    headers,
    id: "custom",
  });
}
