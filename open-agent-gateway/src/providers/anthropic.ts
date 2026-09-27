/**
 * Anthropic-style Messages API provider adapter.
 * POST {baseUrl}/v1/messages with x-api-key + anthropic-version.
 */

import {
  extractTextFromAnthropicContent,
  mapAnthropicUsage,
  mapOpenAIMessagesToAnthropic,
} from "./anthropic-map";
import { ProviderError, throwProviderHttpError } from "./errors";
import type {
  CompleteRequest,
  CompleteResponse,
  Provider,
} from "./types";

export interface AnthropicProviderConfig {
  apiKey: string;
  baseUrl?: string;
  apiVersion?: string;
  defaultMaxTokens?: number;
  /** Optional fetch override (tests). */
  fetch?: typeof fetch;
}

export class AnthropicProvider implements Provider {
  readonly id = "anthropic";
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly apiVersion: string;
  private readonly defaultMaxTokens: number;
  private readonly fetchImpl: typeof fetch;

  constructor(config: AnthropicProviderConfig) {
    if (!config.apiKey) {
      throw new ProviderError("Anthropic API key required", {
        provider: this.id,
        code: "missing_api_key",
      });
    }
    this.apiKey = config.apiKey;
    this.baseUrl = (config.baseUrl ?? "https://api.anthropic.com").replace(/\/+$/, "");
    this.apiVersion = config.apiVersion ?? "2023-06-01";
    this.defaultMaxTokens = config.defaultMaxTokens ?? 1024;
    this.fetchImpl = config.fetch ?? fetch.bind(globalThis);
  }

  async complete(request: CompleteRequest): Promise<CompleteResponse> {
    if (request.stream) {
      return this.completeStreaming(request);
    }

    const { system, messages } = mapOpenAIMessagesToAnthropic(request.messages);
    if (messages.length === 0) {
      throw new ProviderError("At least one non-system message is required", {
        provider: this.id,
        code: "empty_messages",
      });
    }

    const body: Record<string, unknown> = {
      model: request.model,
      max_tokens: request.max_tokens ?? this.defaultMaxTokens,
      messages,
      ...(system ? { system } : {}),
      ...(request.temperature != null ? { temperature: request.temperature } : {}),
      ...(request.top_p != null ? { top_p: request.top_p } : {}),
      ...(request.extra ?? {}),
    };

    const res = await this.fetchImpl(`${this.baseUrl}/v1/messages`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-api-key": this.apiKey,
        "anthropic-version": this.apiVersion,
      },
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

  /**
   * Streaming: Anthropic SSE. Collects text deltas into a single CompleteResponse.
   * (Gateway layer can later expose true SSE passthrough.)
   */
  private async completeStreaming(
    request: CompleteRequest,
  ): Promise<CompleteResponse> {
    const { system, messages } = mapOpenAIMessagesToAnthropic(request.messages);
    const body: Record<string, unknown> = {
      model: request.model,
      max_tokens: request.max_tokens ?? this.defaultMaxTokens,
      messages,
      stream: true,
      ...(system ? { system } : {}),
      ...(request.temperature != null ? { temperature: request.temperature } : {}),
      ...(request.extra ?? {}),
    };

    const res = await this.fetchImpl(`${this.baseUrl}/v1/messages`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-api-key": this.apiKey,
        "anthropic-version": this.apiVersion,
        accept: "text/event-stream",
      },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      await throwProviderHttpError(this.id, res);
    }

    const text = await this.consumeAnthropicSse(res);
    return {
      content: text.content,
      model: text.model ?? request.model,
      finishReason: text.stopReason,
      usage: text.usage,
      raw: { streamed: true },
    };
  }

  private async consumeAnthropicSse(res: Response): Promise<{
    content: string;
    model?: string;
    stopReason?: string;
    usage?: CompleteResponse["usage"];
  }> {
    if (!res.body) {
      throw new ProviderError("Empty SSE body", {
        provider: this.id,
        code: "empty_sse",
      });
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let content = "";
    let model: string | undefined;
    let stopReason: string | undefined;
    let usage: CompleteResponse["usage"];

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n");
      buffer = chunks.pop() ?? "";

      for (const line of chunks) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data:")) continue;
        const payload = trimmed.slice(5).trim();
        if (!payload || payload === "[DONE]") continue;
        try {
          const evt = JSON.parse(payload) as {
            type?: string;
            message?: { model?: string; usage?: unknown };
            delta?: { type?: string; text?: string; stop_reason?: string };
            usage?: unknown;
          };
          if (evt.type === "message_start" && evt.message?.model) {
            model = evt.message.model;
          }
          if (
            evt.type === "content_block_delta" &&
            evt.delta?.type === "text_delta" &&
            typeof evt.delta.text === "string"
          ) {
            content += evt.delta.text;
          }
          if (evt.type === "message_delta") {
            if (evt.delta?.stop_reason) stopReason = evt.delta.stop_reason;
            if (evt.usage) usage = mapAnthropicUsage(evt.usage);
          }
        } catch {
          /* skip malformed SSE lines */
        }
      }
    }

    return { content, model, stopReason, usage };
  }
}

export function createAnthropicProvider(env: {
  ANTHROPIC_API_KEY?: string;
  ANTHROPIC_BASE_URL?: string;
  ANTHROPIC_VERSION?: string;
  ANTHROPIC_MAX_TOKENS?: string;
}): AnthropicProvider | null {
  if (!env.ANTHROPIC_API_KEY) return null;
  return new AnthropicProvider({
    apiKey: env.ANTHROPIC_API_KEY,
    baseUrl: env.ANTHROPIC_BASE_URL,
    apiVersion: env.ANTHROPIC_VERSION,
    defaultMaxTokens: env.ANTHROPIC_MAX_TOKENS
      ? Number(env.ANTHROPIC_MAX_TOKENS)
      : undefined,
  });
}
