/**
 * OpenAI-compatible provider helper for the session agent.
 * Uses Env secrets only — never reads keys from Durable Object state.
 */

import type { ChatMessage, OpenAIFunctionTool, ToolCall } from "./types";
import { DEFAULT_MODEL } from "./types";

export interface ProviderEnv {
  APMIX_BASE_URL?: string;
  PROVIDER_API_KEY?: string;
  DEFAULT_MODEL?: string;
}

export interface CompletionResult {
  role: "assistant";
  content: string | null;
  tool_calls?: ToolCall[];
  model: string;
  finish_reason?: string | null;
}

export async function completeViaProvider(
  env: ProviderEnv,
  messages: ChatMessage[],
  tools?: OpenAIFunctionTool[],
  opts?: { model?: string; temperature?: number; maxTokens?: number },
): Promise<CompletionResult> {
  const base = (env.APMIX_BASE_URL || "https://api.apmix.ai/v1").replace(
    /\/$/,
    "",
  );
  const key = env.PROVIDER_API_KEY;
  if (!key) {
    throw new Error("PROVIDER_API_KEY is not configured");
  }

  const model = opts?.model || env.DEFAULT_MODEL || DEFAULT_MODEL;
  const body: Record<string, unknown> = {
    model,
    messages: messages.map(toOpenAIMessage),
    temperature: opts?.temperature ?? 0.4,
    max_tokens: opts?.maxTokens ?? 1024,
  };
  if (tools?.length) {
    body.tools = tools;
    body.tool_choice = "auto";
  }

  const response = await fetch(`${base}/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${key}`,
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(
      `Provider error ${response.status}: ${text.slice(0, 240)}`,
    );
  }

  const data = (await response.json()) as {
    model?: string;
    choices?: Array<{
      finish_reason?: string | null;
      message?: {
        role?: string;
        content?: string | null;
        tool_calls?: ToolCall[];
      };
    }>;
  };

  const choice = data.choices?.[0];
  const message = choice?.message;
  if (!message) {
    throw new Error("Provider returned no completion choices");
  }

  return {
    role: "assistant",
    content: message.content ?? null,
    tool_calls: Array.isArray(message.tool_calls)
      ? message.tool_calls
      : undefined,
    model: data.model || model,
    finish_reason: choice?.finish_reason ?? null,
  };
}

function toOpenAIMessage(m: ChatMessage): Record<string, unknown> {
  const out: Record<string, unknown> = {
    role: m.role,
    content: m.content ?? "",
  };
  if (m.name) out.name = m.name;
  if (m.tool_call_id) out.tool_call_id = m.tool_call_id;
  if (m.tool_calls?.length) out.tool_calls = m.tool_calls;
  return out;
}
