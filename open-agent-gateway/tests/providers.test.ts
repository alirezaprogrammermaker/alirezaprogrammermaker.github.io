import { describe, expect, it, vi } from "vitest";
import { OpenAICompatibleProvider } from "../src/providers/openai-compatible";
import { createApmixProvider, APMIX_DEFAULT_BASE_URL } from "../src/providers/apmix";
import { assertSafeBaseUrl } from "../src/providers/url-guard";
import { normalizeOpenAIChatResponse } from "../src/providers/normalize";
import { redactSecrets } from "../src/providers/errors";

describe("url-guard", () => {
  it("allows https public hosts", () => {
    const u = assertSafeBaseUrl("https://api.apmix.ai/v1/");
    expect(u.hostname).toBe("api.apmix.ai");
  });

  it("blocks http and localhost", () => {
    expect(() => assertSafeBaseUrl("http://api.apmix.ai/v1")).toThrow();
    expect(() => assertSafeBaseUrl("https://localhost/v1")).toThrow();
    expect(() => assertSafeBaseUrl("https://127.0.0.1/v1")).toThrow();
  });
});

describe("normalizeOpenAIChatResponse", () => {
  it("maps a standard completion", () => {
    const r = normalizeOpenAIChatResponse(
      {
        id: "chatcmpl_x",
        object: "chat.completion",
        created: 1,
        model: "gpt-6-luna-free",
        choices: [
          {
            index: 0,
            message: { role: "assistant", content: "hi" },
            finish_reason: "stop",
          },
        ],
        usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
      },
      "fallback",
    );
    expect(r.message.content).toBe("hi");
    expect(r.usage?.total_tokens).toBe(2);
  });
});

describe("redactSecrets", () => {
  it("redacts apmix-looking tokens", () => {
    const s = redactSecrets("Bearer apx_live_ABCDEFGHijklmnop");
    expect(s).not.toContain("apx_live_ABCDEF");
    expect(s).toContain("[REDACTED]");
  });
});

describe("OpenAICompatibleProvider", () => {
  it("posts non-stream and normalizes", async () => {
    const fetchMock = vi.fn(async () => {
      return new Response(
        JSON.stringify({
          id: "1",
          created: 10,
          model: "m",
          choices: [
            {
              index: 0,
              message: { role: "assistant", content: "ok" },
              finish_reason: "stop",
            },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    });

    const p = new OpenAICompatibleProvider({
      id: "openai",
      baseUrl: "https://api.openai.com/v1",
      apiKey: "sk-test",
      fetch: fetchMock as unknown as typeof fetch,
    });

    const result = await p.complete({
      model: "m",
      messages: [{ role: "user", content: "x" }],
    });
    expect(result.message.content).toBe("ok");
    expect(fetchMock).toHaveBeenCalledOnce();
    const call = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(call[0])).toContain("/chat/completions");
    expect(call[1].method).toBe("POST");
  });

  it("streams SSE bytes", async () => {
    const sse =
      'data: {"id":"1","object":"chat.completion.chunk","created":1,"model":"m","choices":[{"index":0,"delta":{"content":"a"},"finish_reason":null}]}\n\n' +
      "data: [DONE]\n\n";
    const fetchMock = vi.fn(async () => {
      return new Response(sse, {
        status: 200,
        headers: { "content-type": "text/event-stream" },
      });
    });
    const p = new OpenAICompatibleProvider({
      id: "openai",
      baseUrl: "https://api.openai.com/v1",
      apiKey: "sk-test",
      fetch: fetchMock as unknown as typeof fetch,
    });
    const stream = await p.complete({
      model: "m",
      messages: [{ role: "user", content: "x" }],
      stream: true,
    });
    const text = await new Response(stream).text();
    expect(text).toContain("[DONE]");
    expect(text).toContain('"content":"a"');
  });
});

describe("ApmixProvider", () => {
  it("defaults base URL", () => {
    const p = createApmixProvider("apx_live_testkey_xxxxxxxx");
    expect(p.id).toBe("apmix");
    expect(p.defaultModel).toBe("gpt-6-luna-free");
    expect(APMIX_DEFAULT_BASE_URL).toContain("apmix.ai");
  });
});
