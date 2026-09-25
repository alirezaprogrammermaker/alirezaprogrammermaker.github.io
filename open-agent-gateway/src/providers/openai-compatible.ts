/**
 * OpenAI-compatible chat.completions adapter (Workers fetch).
 */

import { mapHttpError, ProviderError } from "./errors";
import { normalizeOpenAIChatResponse } from "./normalize";
import { encodeSseDone } from "./sse";
import type {
  CompleteParams,
  CompleteResult,
  LLMProvider,
  ProviderConfig,
  ProviderId,
} from "./types";
import { assertSafeBaseUrl, joinUrl } from "./url-guard";

const PASSTHROUGH_KEYS = [
  "temperature",
  "top_p",
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
  "n",
  "logit_bias",
  "logprobs",
  "top_logprobs",
] as const;

function buildBody(params: CompleteParams, stream: boolean): Record<string, unknown> {
  const body: Record<string, unknown> = {
    model: params.model,
    messages: params.messages,
    stream,
  };
  for (const key of PASSTHROUGH_KEYS) {
    const v = (params as unknown as Record<string, unknown>)[key];
    if (v !== undefined) body[key] = v;
  }
  if (params.extras) {
    for (const [k, v] of Object.entries(params.extras)) {
      if (v !== undefined && !(k in body) && k !== "model" && k !== "messages" && k !== "stream") {
        body[k] = v;
      }
    }
  }
  return body;
}

export class OpenAICompatibleProvider implements LLMProvider {
  readonly id: ProviderId;
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly chatPath: string;
  private readonly defaultHeaders: Record<string, string>;
  private readonly fetchImpl: typeof fetch;

  constructor(config: ProviderConfig) {
    const url = assertSafeBaseUrl(config.baseUrl, {
      allowPrivate: config.allowPrivateBaseUrl,
    });
    this.id = config.id;
    this.baseUrl = url.toString().replace(/\/+$/, "");
    this.apiKey = config.apiKey;
    this.chatPath = config.chatPath ?? "/chat/completions";
    this.defaultHeaders = { ...(config.defaultHeaders ?? {}) };
    this.fetchImpl = config.fetch ?? fetch;

    if (!this.apiKey) {
      throw new ProviderError(`Missing API key for provider ${config.id}`, {
        code: "config",
        providerId: String(config.id),
      });
    }
  }

  complete(params: CompleteParams & { stream: true }): Promise<ReadableStream<Uint8Array>>;
  complete(params: CompleteParams & { stream?: false }): Promise<CompleteResult>;
  complete(
    params: CompleteParams,
  ): Promise<CompleteResult | ReadableStream<Uint8Array>>;
  async complete(
    params: CompleteParams,
  ): Promise<CompleteResult | ReadableStream<Uint8Array>> {
    if (params.stream) {
      return this.completeStream(params);
    }
    return this.completeOnce(params);
  }

  async completeStream(params: CompleteParams): Promise<ReadableStream<Uint8Array>> {
    const res = await this.request(params, true);
    if (!res.body) {
      throw new ProviderError("Upstream stream missing body", {
        code: "upstream",
        providerId: String(this.id),
        status: res.status,
      });
    }
    // Passthrough OpenAI SSE; append [DONE] if upstream closes without it.
    const upstream = res.body;
    return new ReadableStream<Uint8Array>({
      async start(controller) {
        const reader = upstream.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        let sawDone = false;
        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            if (value) {
              buf += decoder.decode(value, { stream: true });
              if (buf.includes("[DONE]")) sawDone = true;
              controller.enqueue(value);
              // keep buf bounded
              if (buf.length > 4096) buf = buf.slice(-1024);
            }
          }
          if (!sawDone) controller.enqueue(encodeSseDone());
          controller.close();
        } catch (err) {
          controller.error(err);
        } finally {
          try {
            reader.releaseLock();
          } catch {
            /* ignore */
          }
        }
      },
      cancel() {
        try {
          void upstream.cancel();
        } catch {
          /* ignore */
        }
      },
    });
  }

  private async completeOnce(params: CompleteParams): Promise<CompleteResult> {
    const res = await this.request(params, false);
    const text = await res.text();
    let json: unknown;
    try {
      json = JSON.parse(text);
    } catch {
      throw new ProviderError("Upstream returned invalid JSON", {
        code: "parse",
        providerId: String(this.id),
        status: res.status,
        bodySnippet: text.slice(0, 300),
      });
    }
    return normalizeOpenAIChatResponse(json, params.model);
  }

  private async request(params: CompleteParams, stream: boolean): Promise<Response> {
    const url = joinUrl(this.baseUrl, this.chatPath);
    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.apiKey}`,
      "Content-Type": "application/json",
      Accept: stream ? "text/event-stream" : "application/json",
      ...this.defaultHeaders,
    };

    let res: Response;
    try {
      res = await this.fetchImpl(url, {
        method: "POST",
        headers,
        body: JSON.stringify(buildBody(params, stream)),
        signal: params.signal,
      });
    } catch (err) {
      throw new ProviderError(`Network error talking to ${this.id}`, {
        code: "network",
        providerId: String(this.id),
        retryable: true,
        cause: err,
      });
    }

    if (!res.ok) {
      const bodyText = await res.text().catch(() => "");
      throw mapHttpError(res.status, bodyText, String(this.id));
    }
    return res;
  }
}

export function createOpenAICompatibleProvider(
  config: ProviderConfig,
): OpenAICompatibleProvider {
  return new OpenAICompatibleProvider(config);
}
