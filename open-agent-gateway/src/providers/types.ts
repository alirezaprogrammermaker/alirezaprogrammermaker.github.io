/**
 * Shared provider adapter contract.
 * // SLOT w02: OpenAI-compatible + apmix adapters
 * // SLOT w03: Anthropic-style + custom baseURL adapters
 */

export type ProviderId = "openai" | "apmix" | "anthropic" | "custom";

export type ChatRole = "system" | "user" | "assistant" | "tool";

export interface ChatMessage {
  role: ChatRole;
  content: string;
  name?: string;
  tool_call_id?: string;
}

export interface CompleteRequest {
  model: string;
  messages: ChatMessage[];
  stream?: boolean;
  temperature?: number;
  max_tokens?: number;
  /** Extra OpenAI-compatible fields forwarded when supported */
  [key: string]: unknown;
}

export interface CompleteUsage {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
}

export interface CompleteResult {
  content: string;
  finish_reason?: string | null;
  usage?: CompleteUsage;
  /** Raw upstream payload for debugging (never log secrets) */
  raw?: unknown;
}

/**
 * Every provider implements this. Streaming may return a ReadableStream
 * when stream=true (filled by w02/w03/w05).
 */
export interface ProviderAdapter {
  readonly id: ProviderId;
  complete(req: CompleteRequest): Promise<CompleteResult | ReadableStream>;
}
