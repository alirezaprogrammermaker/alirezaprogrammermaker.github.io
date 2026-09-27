/**
 * Shared types for the gateway session agent (w06).
 * Provider secrets must live in Env bindings — never in synced state.
 */

export type ChatRole = "system" | "user" | "assistant" | "tool";

export interface ToolCallFunction {
  name: string;
  arguments: string;
}

export interface ToolCall {
  id: string;
  type: "function";
  function: ToolCallFunction;
}

export interface ChatMessage {
  id?: string;
  role: ChatRole;
  content?: string | null;
  name?: string;
  tool_call_id?: string;
  tool_calls?: ToolCall[];
  createdAt?: string;
}

export interface SessionMeta {
  sessionId: string;
  createdAt: string;
  updatedAt: string;
  model: string;
  providerId: string;
  messageCount: number;
}

export interface SessionPreferences {
  temperature?: number;
  maxTokens?: number;
  systemPrompt?: string;
  theme?: string;
  locale?: string;
  [key: string]: string | number | boolean | undefined;
}

export interface LastToolRunSummary {
  id: string;
  name: string;
  status: "completed" | "failed";
  at: string;
}

/** Synced Durable Object state (setState). Keep small — tool logs go to SQL. */
export interface GatewayState {
  version: number;
  messages: ChatMessage[];
  sessionMeta: SessionMeta;
  preferences: SessionPreferences;
  lastToolRun: LastToolRunSummary | null;
}

export interface ProviderInfo {
  id: string;
  name: string;
  baseURL: string;
  models: string[];
}

export interface ToolJsonSchema {
  type: "object";
  properties?: Record<string, unknown>;
  required?: string[];
  additionalProperties?: boolean;
}

export interface ToolDefinition {
  name: string;
  description: string;
  parameters: ToolJsonSchema;
  handler: (
    params: Record<string, unknown>,
    ctx: ToolContext,
  ) => Promise<string> | string;
}

export interface ToolContext {
  agentName: string;
  sessionId: string;
}

export interface OpenAIFunctionTool {
  type: "function";
  function: {
    name: string;
    description: string;
    parameters: ToolJsonSchema;
  };
}

export interface WsEnvelope<T = unknown> {
  type: string;
  ok: boolean;
  payload?: T;
  error?: string;
}

export const MAX_SYNCED_MESSAGES = 100;
export const MAX_TOOL_ROUNDS = 5;
export const DEFAULT_MODEL = "gpt-6-luna-free";
export const DEFAULT_PROVIDER_ID = "apmix";
