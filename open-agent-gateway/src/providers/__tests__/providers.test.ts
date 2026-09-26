import { describe, expect, it, vi } from "vitest";
import { AnthropicProvider } from "../anthropic";
import { CustomBaseURLProvider } from "../custom";

describe("AnthropicProvider", () => {
  it("POSTs /v1/messages with x-api-key and anthropic-version", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      expect(url).toBe("https://api.anthropic.com/v1/messages");
      const headers = new Headers(init?.headers);
      expect(headers.get("x-api-key")).toBe("test-key");
      expect(headers.get("anthropic-version")).toBe("2023-06-01");
      const body = JSON.parse(String(init?.body));
      expect(body.system).toBe("sys");
      expect(body.messages[0]).toEqual({ role: "user", content: "hi" });
      return new Response(
        JSON.stringify({
          content: [{ type: "text", text: "hello" }],
          model: "claude-test",
          stop_reason: "end_turn",
          usage: { input_tokens: 3, output_tokens: 1 },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    });

    const provider = new AnthropicProvider({
      apiKey: "test-key",
      fetch: fetchMock as unknown as typeof fetch,
    });

    const result = await provider.complete({
      model: "claude-test",
      messages: [
        { role: "system", content: "sys" },
        { role: "user", content: "hi" },
      ],
    });

    expect(result.content).toBe("hello");
    expect(result.model).toBe("claude-test");
    expect(result.usage?.promptTokens).toBe(3);
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});

describe("CustomBaseURLProvider", () => {
  it("calls OpenAI-compatible chat completions at custom base URL", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      expect(url).toBe("https://api.apmix.ai/v1/chat/completions");
      const headers = new Headers(init?.headers);
      expect(headers.get("authorization")).toBe("Bearer custom-key");
      return new Response(
        JSON.stringify({
          choices: [{ message: { content: "pong" }, finish_reason: "stop" }],
          model: "gpt-6-luna-free",
          usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
        }),
        { status: 200 },
      );
    });

    const provider = new CustomBaseURLProvider({
      baseUrl: "https://api.apmix.ai/v1",
      apiKey: "custom-key",
      fetch: fetchMock as unknown as typeof fetch,
    });

    const result = await provider.complete({
      model: "gpt-6-luna-free",
      messages: [{ role: "user", content: "ping" }],
    });

    expect(result.content).toBe("pong");
    expect(result.usage?.totalTokens).toBe(2);
  });

  it("rejects non-http baseUrl", () => {
    expect(
      () => new CustomBaseURLProvider({ baseUrl: "ftp://evil" }),
    ).toThrow(/http/);
  });
});
