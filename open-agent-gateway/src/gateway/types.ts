/**
 * OpenAI-compatible chat completions types for the gateway.
 * Slice: w05 — /v1/chat/completions
 */

export type ChatRole = "system" | "user" | "assistant" | "tool" | "function" | "developer";

export interface ChatMessage {
  role: ChatRole | string;
  content: string | null | Array<Record<string, unknown>>;
  name?: string;
  tool_call_id?: string;
  tool_calls?: unknown[];
}

export interface ChatCompletionRequest {
  model: string;
  messages: ChatMessage[];
  stream?: boolean;
  temperature?: number;
  top_p?: number;
  n?: number;
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
  /** Passthrough bag for provider-specific knobs */
  [key: string]: unknown;
}

export interface ChatCompletionChoice {
  index: number;
  message: {
    role: "assistant";
    content: string | null;
    tool_calls?: unknown[];
  };
  finish_reason: string | null;
  logprobs?: unknown;
}

export interface ChatCompletionUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface ChatCompletionResponse {
  id: string;
  object: "chat.completion";
  created: number;
  model: string;
  choices: ChatCompletionChoice[];
  usage?: ChatCompletionUsage;
  system_fingerprint?: string | null;
}

export interface ChatCompletionChunkDelta {
  role?: "assistant";
  content?: string | null;
  tool_calls?: unknown[];
}

export interface ChatCompletionChunkChoice {
  index: number;
  delta: ChatCompletionChunkDelta;
  finish_reason: string | null;
  logprobs?: unknown;
}

export interface ChatCompletionChunk {
  id: string;
  object: "chat.completion.chunk";
  created: number;
  model: string;
  choices: ChatCompletionChunkChoice[];
  usage?: ChatCompletionUsage | null;
}

/** Provider adapter contract (owned by w02; referenced here). */
export interface CompleteParams {
  model: string;
  messages: ChatMessage[];
  stream?: boolean;
  signal?: AbortSignal;
  /** Original validated body for passthrough of optional params */
  extras?: Record<string, unknown>;
}

export interface CompleteResult {
  id: string;
  model: string;
  created: number;
  message: { role: "assistant"; content: string | null; tool_calls?: unknown[] };
  finish_reason: string | null;
  usage?: ChatCompletionUsage;
}

export interface ProviderAdapter {
  complete(params: CompleteParams): Promise<CompleteResult>;
  /**
   * When stream=true, returns an OpenAI-compatible SSE ReadableStream
   * (bytes of `data: {...}\n\n` ending with `data: [DONE]\n\n`).
   */
  completeStream?(params: CompleteParams): Promise<ReadableStream<Uint8Array>>;
}

export interface GatewayAuthContext {
  keyId: string;
  /** Hashed key id / subject — never the raw secret */
  subject?: string;
}

export interface GatewayEnv {
  /** Issued gateway API keys store (KV) — w04 */
  API_KEYS?: KVNamespace;
  /** Upstream provider API key (secret binding) */
  UPSTREAM_API_KEY?: string;
  /** Default OpenAI-compatible base, e.g. https://api.apmix.ai/v1 */
  UPSTREAM_BASE_URL?: string;
  /** Default model when client omits or for rewrite policy */
  DEFAULT_MODEL?: string;
}

export type OpenAIErrorType =
  | "invalid_request_error"
  | "authentication_error"
  | "permission_error"
  | "rate_limit_error"
  | "server_error"
  | "api_error";

export interface OpenAIErrorBody {
  error: {
    message: string;
    type: OpenAIErrorType;
    param?: string | null;
    code?: string | null;
  };
}
