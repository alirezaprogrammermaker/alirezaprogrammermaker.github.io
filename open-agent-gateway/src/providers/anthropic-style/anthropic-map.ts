/**
 * OpenAI-style ↔ Anthropic Messages API mapping helpers (pure).
 */

import type { ChatMessage } from "./types";

export interface AnthropicMessage {
  role: "user" | "assistant";
  content: string | AnthropicContentBlock[];
}

export interface AnthropicContentBlock {
  type: string;
  text?: string;
  [key: string]: unknown;
}

export interface AnthropicMessagesInput {
  system?: string;
  messages: AnthropicMessage[];
}

function contentToString(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((part) => {
        if (typeof part === "string") return part;
        if (part && typeof part === "object" && "text" in part) {
          return String((part as { text?: unknown }).text ?? "");
        }
        return "";
      })
      .filter(Boolean)
      .join("\n");
  }
  if (content == null) return "";
  return String(content);
}

/**
 * Pull system/developer messages into Anthropic's top-level `system` string.
 * Remaining turns become user/assistant only (tool → user text for v1).
 */
export function mapOpenAIMessagesToAnthropic(
  messages: ChatMessage[],
): AnthropicMessagesInput {
  const systemParts: string[] = [];
  const mapped: AnthropicMessage[] = [];

  for (const msg of messages) {
    const text = contentToString(msg.content);
    const role = (msg.role || "user").toLowerCase();

    if (role === "system" || role === "developer") {
      if (text) systemParts.push(text);
      continue;
    }

    if (role === "assistant") {
      mapped.push({ role: "assistant", content: text });
      continue;
    }

    // user, tool, or unknown → user
    const prefix = role === "tool" ? `[tool${msg.name ? `:${msg.name}` : ""}] ` : "";
    mapped.push({ role: "user", content: prefix + text });
  }

  // Anthropic requires alternating roles starting with user; merge consecutive same-role.
  const coalesced: AnthropicMessage[] = [];
  for (const m of mapped) {
    const prev = coalesced[coalesced.length - 1];
    if (prev && prev.role === m.role && typeof prev.content === "string" && typeof m.content === "string") {
      prev.content = `${prev.content}\n${m.content}`;
    } else {
      coalesced.push({ ...m });
    }
  }

  // If first message is assistant, prepend empty user turn.
  if (coalesced.length > 0 && coalesced[0].role === "assistant") {
    coalesced.unshift({ role: "user", content: "(continued)" });
  }

  const system = systemParts.length ? systemParts.join("\n\n") : undefined;
  return { system, messages: coalesced };
}

/** Extract plain text from Anthropic content blocks (skip tool_use for text). */
export function extractTextFromAnthropicContent(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return content == null ? "" : String(content);

  const parts: string[] = [];
  for (const block of content) {
    if (!block || typeof block !== "object") continue;
    const b = block as AnthropicContentBlock;
    if (b.type === "text" && typeof b.text === "string") {
      parts.push(b.text);
    } else if (b.type === "thinking" && typeof b.text === "string") {
      // Optional: omit thinking from user-facing content by default
      continue;
    }
    // tool_use / tool_result ignored for text extraction; raw kept by caller
  }
  return parts.join("");
}

export function mapAnthropicUsage(usage: unknown): {
  promptTokens?: number;
  completionTokens?: number;
  totalTokens?: number;
} | undefined {
  if (!usage || typeof usage !== "object") return undefined;
  const u = usage as Record<string, number>;
  const promptTokens = u.input_tokens ?? u.prompt_tokens;
  const completionTokens = u.output_tokens ?? u.completion_tokens;
  const totalTokens =
    u.total_tokens ??
    (promptTokens != null && completionTokens != null
      ? promptTokens + completionTokens
      : undefined);
  return { promptTokens, completionTokens, totalTokens };
}
