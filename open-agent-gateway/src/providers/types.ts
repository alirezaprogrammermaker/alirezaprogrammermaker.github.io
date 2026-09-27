/**
 * Provider abstraction for open-agent-gateway (w02).
 * Contract shared with w05 gateway + w03 anthropic/custom adapters.
 */

export type ProviderId = "openai" | "apmix" | "anthropic" | "custom" | (string & {});

export type ChatRole =
  | "system"
  | "user"
  | "assistant"
  | "tool"
  | "function"
  | "developer";

export interface ChatMessage {
  role: ChatRole | string;
  content: string | null | Array<Record<string, unknown>>;
  name?: string;
  tool_call_id?: string;
  tool_calls?: unknown[];
}

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

/** Normalized non-stream completion result for gateway use. */
export interface CompleteResult {
  id: string;
  model: string;
  created: number;
  message: {
    role: "assistant";
    content: string | null;
    tool_calls?: unknown[];
  };
  finish_reason: string | null;
  usage?: TokenUsage;
  /** Upstream OpenAI-shaped object when available */
  raw?: unknown;
}

export interface StreamChunkDelta {
  role?: "assistant";
  content?: string | null;
  tool_calls?: unknown[];
}

/** OpenAI-compatible chat.completion.chunk choice. */
export interface StreamChunk {
  id: string;
  object: "chat.completion.chunk";
  created: number;
  model: string;
  choices: Array<{
    index: number;
    delta: StreamChunkDelta;
    finish_reason: string | null;
  }>;
  usage?: TokenUsage | null;
}

export interface CompleteParams {
  model: string;
  messages: ChatMessage[];
  stream?: boolean;
  signal?: AbortSignal;
  /** Per-request timeout; composed with signal when both set */
  timeoutMs?: number;
  temperature?: number;
  top_p?: number;
  max_tokens?: number;
  max_completion_tokens?: number;
  stop?: string | string[] | null;
  presence_penalty?: number;
  frequency_penalty?: number;
  user?: string;
  seed?: number;
  tools?: unknown[];
  tool_choice?: unknown;
  response_format?: unknown;
  stream_options?: { include_usage?: boolean };
  /** Extra OpenAI-compatible fields forwarded upstream */
  extras?: Record<string, unknown>;
}

export interface ProviderConfig {
  id: ProviderId;
  baseUrl: string;
  apiKey: string;
  defaultHeaders?: Record<string, string>;
  /** Appended path; default `/chat/completions` relative to baseUrl */
  chatPath?: string;
  /** Skip SSRF guard (tests / private networks only) */
  allowPrivateBaseUrl?: boolean;
  defaultModel?: string;
  /** Default request timeout (ms); overridable per call via CompleteParams.timeoutMs */
  timeoutMs?: number;
  fetch?: typeof fetch;
}

/**
 * Core adapter: `complete({ model, messages, stream? })`.
 * Non-stream → CompleteResult; stream → SSE ReadableStream (OpenAI bytes).
 */
export interface LLMProvider {
  readonly id: ProviderId;

  complete(params: CompleteParams & { stream: true }): Promise<ReadableStream<Uint8Array>>;
  complete(params: CompleteParams & { stream?: false }): Promise<CompleteResult>;
  complete(
    params: CompleteParams,
  ): Promise<CompleteResult | ReadableStream<Uint8Array>>;

  /** Explicit stream helper for gateway (w05). */
  completeStream(params: CompleteParams): Promise<ReadableStream<Uint8Array>>;
}

/** Alias matching w05 naming. */
export type ProviderAdapter = LLMProvider;
