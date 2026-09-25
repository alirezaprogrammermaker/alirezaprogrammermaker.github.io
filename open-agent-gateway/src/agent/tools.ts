/**
 * Built-in tools for GatewaySessionAgent.
 * Handlers receive a ToolHost so they can touch SQL / schedule / state safely.
 */

import type {
  OpenAIFunctionTool,
  ProviderInfo,
  ToolDefinition,
  ToolJsonSchema,
} from "./types";

export interface ToolHost {
  sessionId: string;
  getPreference: (key: string) => string | number | boolean | undefined;
  setPreference: (key: string, value: string) => void;
  memorySet: (key: string, value: string) => void;
  memoryGet: (key: string) => string | null;
  searchHistory: (query: string, limit: number) => Array<{
    role: string;
    content: string;
  }>;
  clearHistory: () => void;
  listProviders: () => ProviderInfo[];
  schedulePing: (delaySeconds: number, message: string) => Promise<string>;
  nowIso: () => string;
}

function schema(
  properties: Record<string, unknown>,
  required: string[] = [],
): ToolJsonSchema {
  return {
    type: "object",
    properties,
    required,
    additionalProperties: false,
  };
}

export function createBuiltinTools(host: ToolHost): ToolDefinition[] {
  return [
    {
      name: "echo",
      description: "Return the supplied text unchanged (debug / smoke tool).",
      parameters: schema(
        { text: { type: "string", description: "Text to echo." } },
        ["text"],
      ),
      handler: (params) =>
        JSON.stringify({ echoed: String(params.text ?? "") }),
    },
    {
      name: "memory_set",
      description: "Store or replace a durable key/value in session SQLite memory.",
      parameters: schema(
        {
          key: { type: "string", minLength: 1 },
          value: { type: "string" },
        },
        ["key", "value"],
      ),
      handler: (params) => {
        const key = String(params.key ?? "").trim();
        if (!key) return JSON.stringify({ ok: false, error: "key required" });
        host.memorySet(key, String(params.value ?? ""));
        return JSON.stringify({ ok: true, key });
      },
    },
    {
      name: "memory_get",
      description: "Retrieve a durable memory value by key for this session.",
      parameters: schema(
        { key: { type: "string", minLength: 1 } },
        ["key"],
      ),
      handler: (params) => {
        const key = String(params.key ?? "").trim();
        const value = host.memoryGet(key);
        return JSON.stringify({
          ok: value !== null,
          key,
          value,
        });
      },
    },
    {
      name: "list_providers",
      description: "List LLM providers available through the gateway.",
      parameters: schema({}),
      handler: () => JSON.stringify({ providers: host.listProviders() }),
    },
    {
      name: "schedule_ping",
      description:
        "Schedule a WebSocket broadcast ping after delay_seconds (Durable Object alarm).",
      parameters: schema(
        {
          delay_seconds: { type: "integer", minimum: 1, maximum: 86400 },
          message: { type: "string", minLength: 1 },
        },
        ["delay_seconds", "message"],
      ),
      handler: async (params) => {
        const delay = Math.max(1, Number(params.delay_seconds) || 1);
        const message = String(params.message ?? "ping");
        const id = await host.schedulePing(delay, message);
        return JSON.stringify({ ok: true, scheduleId: id, delay_seconds: delay });
      },
    },
    {
      name: "search_history",
      description: "Search this session's conversation history (case-insensitive).",
      parameters: schema(
        {
          query: { type: "string", minLength: 1 },
          limit: { type: "integer", minimum: 1, maximum: 100, default: 20 },
        },
        ["query"],
      ),
      handler: (params) => {
        const query = String(params.query ?? "");
        const limit = Math.min(100, Math.max(1, Number(params.limit) || 20));
        const matches = host.searchHistory(query, limit);
        return JSON.stringify({ ok: true, count: matches.length, matches });
      },
    },
    {
      name: "clear_history",
      description: "Clear synced chat history. Requires confirm=true.",
      parameters: schema(
        { confirm: { type: "boolean", description: "Must be true." } },
        ["confirm"],
      ),
      handler: (params) => {
        if (params.confirm !== true) {
          return JSON.stringify({
            ok: false,
            error: "confirm must be true",
          });
        }
        host.clearHistory();
        return JSON.stringify({ ok: true, cleared: true });
      },
    },
    {
      name: "set_preference",
      description: "Set a named session preference (synced via setState).",
      parameters: schema(
        {
          key: { type: "string", minLength: 1 },
          value: { type: "string" },
        },
        ["key", "value"],
      ),
      handler: (params) => {
        const key = String(params.key ?? "").trim();
        if (!key) return JSON.stringify({ ok: false, error: "key required" });
        host.setPreference(key, String(params.value ?? ""));
        return JSON.stringify({
          ok: true,
          key,
          value: host.getPreference(key),
        });
      },
    },
  ];
}

export function toOpenAITools(defs: ToolDefinition[]): OpenAIFunctionTool[] {
  return defs.map((t) => ({
    type: "function",
    function: {
      name: t.name,
      description: t.description,
      parameters: t.parameters,
    },
  }));
}

export function defaultProviders(
  apmixBaseURL?: string,
): ProviderInfo[] {
  return [
    {
      id: "apmix",
      name: "apmix (OpenAI-compatible)",
      baseURL: apmixBaseURL || "https://api.apmix.ai/v1",
      models: ["gpt-6-luna-free"],
    },
    {
      id: "openai",
      name: "OpenAI-compatible (custom)",
      baseURL: "https://api.openai.com/v1",
      models: ["gpt-4o-mini"],
    },
    {
      id: "anthropic",
      name: "Anthropic-style (via adapter)",
      baseURL: "https://api.anthropic.com",
      models: ["claude-sonnet"],
    },
  ];
}
