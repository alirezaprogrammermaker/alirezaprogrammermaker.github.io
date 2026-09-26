/**
 * Normalize unknown OpenAI chat.completion JSON into CompleteResult.
 */

import { ProviderError } from "./errors";
import type { CompleteResult, TokenUsage } from "./types";

function asRecord(v: unknown): Record<string, unknown> | null {
  return v !== null && typeof v === "object" ? (v as Record<string, unknown>) : null;
}

function parseUsage(raw: unknown): TokenUsage | undefined {
  const u = asRecord(raw);
  if (!u) return undefined;
  const prompt = Number(u.prompt_tokens ?? 0);
  const completion = Number(u.completion_tokens ?? 0);
  const total = Number(u.total_tokens ?? prompt + completion);
  if (!Number.isFinite(prompt) || !Number.isFinite(completion)) return undefined;
  return { prompt_tokens: prompt, completion_tokens: completion, total_tokens: total };
}

export function normalizeOpenAIChatResponse(
  raw: unknown,
  fallbackModel: string,
): CompleteResult {
  const root = asRecord(raw);
  if (!root) {
    throw new ProviderError("Upstream returned non-object JSON", { code: "parse" });
  }
  const choices = root.choices;
  if (!Array.isArray(choices) || choices.length === 0) {
    throw new ProviderError("Upstream returned no choices", {
      code: "parse",
      bodySnippet: JSON.stringify(raw).slice(0, 300),
    });
  }
  const choice = asRecord(choices[0]) ?? {};
  const message = asRecord(choice.message) ?? {};
  const role = message.role === "assistant" ? "assistant" : "assistant";
  let content: string | null = null;
  if (typeof message.content === "string") content = message.content;
  else if (message.content === null) content = null;
  else if (Array.isArray(message.content)) {
    content = message.content
      .map((part) => {
        const p = asRecord(part);
        if (p && typeof p.text === "string") return p.text;
        return "";
      })
      .join("");
  }

  const id = typeof root.id === "string" ? root.id : `chatcmpl_${crypto.randomUUID()}`;
  const model = typeof root.model === "string" ? root.model : fallbackModel;
  const created =
    typeof root.created === "number" ? root.created : Math.floor(Date.now() / 1000);

  return {
    id,
    model,
    created,
    message: {
      role,
      content,
      tool_calls: message.tool_calls as unknown[] | undefined,
    },
    finish_reason:
      choice.finish_reason === undefined || choice.finish_reason === null
        ? null
        : String(choice.finish_reason),
    usage: parseUsage(root.usage),
    raw,
  };
}
