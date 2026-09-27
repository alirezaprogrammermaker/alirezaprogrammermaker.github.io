/**
 * Shared provider contract for open-agent-gateway.
 * w03 delivers Anthropic-style + Custom baseURL adapters against this interface.
 * w02 owns OpenAI-compatible + apmix; keep this file aligned if w02 lands a canonical types.ts.
 */

export type ChatRole = "system" | "user" | "assistant" | "tool" | "developer";

export interface ChatMessage {
  role: ChatRole | string;
  content: string;
  name?: string;
}

export interface CompleteRequest {
  model: string;
  messages: ChatMessage[];
  stream?: boolean;
  max_tokens?: number;
  temperature?: number;
  top_p?: number;
  stop?: string | string[];
  /** Extra provider-specific fields (forwarded when safe). */
  extra?: Record<string, unknown>;
}

export interface TokenUsage {
  promptTokens?: number;
  completionTokens?: number;
  totalTokens?: number;
}

export interface CompleteResponse {
  content: string;
  model: string;
  usage?: TokenUsage;
  finishReason?: string;
  raw?: unknown;
}

export interface Provider {
  readonly id: string;
  complete(request: CompleteRequest): Promise<CompleteResponse>;
}

export type AuthHeaderMode = "bearer" | "x-api-key" | "none";
export type RequestStyle = "openai" | "anthropic";
