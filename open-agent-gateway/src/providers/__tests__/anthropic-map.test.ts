/**
 * Pure mapping tests for Anthropic message conversion.
 * Runnable once vitest lands (w09); kept copy-pasteable.
 */

import { describe, expect, it } from "vitest";
import {
  extractTextFromAnthropicContent,
  mapOpenAIMessagesToAnthropic,
} from "../anthropic-map";

describe("mapOpenAIMessagesToAnthropic", () => {
  it("moves system to top-level and keeps user", () => {
    const result = mapOpenAIMessagesToAnthropic([
      { role: "system", content: "Be concise." },
      { role: "user", content: "Hi" },
    ]);
    expect(result.system).toBe("Be concise.");
    expect(result.messages).toEqual([{ role: "user", content: "Hi" }]);
  });

  it("concatenates multiple system messages", () => {
    const result = mapOpenAIMessagesToAnthropic([
      { role: "system", content: "A" },
      { role: "developer", content: "B" },
      { role: "user", content: "Q" },
    ]);
    expect(result.system).toBe("A\n\nB");
    expect(result.messages).toHaveLength(1);
  });

  it("coalesces consecutive same-role turns", () => {
    const result = mapOpenAIMessagesToAnthropic([
      { role: "user", content: "one" },
      { role: "user", content: "two" },
      { role: "assistant", content: "ok" },
    ]);
    expect(result.messages[0]).toEqual({ role: "user", content: "one\ntwo" });
    expect(result.messages[1]).toEqual({ role: "assistant", content: "ok" });
  });

  it("prepends user if first turn is assistant", () => {
    const result = mapOpenAIMessagesToAnthropic([
      { role: "assistant", content: "prev" },
      { role: "user", content: "next" },
    ]);
    expect(result.messages[0].role).toBe("user");
    expect(result.messages[1]).toEqual({ role: "assistant", content: "prev" });
  });

  it("returns empty messages for system-only input", () => {
    const result = mapOpenAIMessagesToAnthropic([
      { role: "system", content: "only" },
    ]);
    expect(result.system).toBe("only");
    expect(result.messages).toEqual([]);
  });
});

describe("extractTextFromAnthropicContent", () => {
  it("joins text blocks and skips tool_use", () => {
    const text = extractTextFromAnthropicContent([
      { type: "text", text: "Hello" },
      { type: "tool_use", id: "1", name: "x", input: {} },
      { type: "text", text: " world" },
    ]);
    expect(text).toBe("Hello world");
  });

  it("handles plain string content", () => {
    expect(extractTextFromAnthropicContent("raw")).toBe("raw");
  });
});
