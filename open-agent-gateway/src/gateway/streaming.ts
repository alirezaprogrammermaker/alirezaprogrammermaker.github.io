/**
 * SSE streaming helpers for OpenAI-compatible chat.completion.chunk.
 */

import type { ChatCompletionChunk, ChatCompletionUsage } from "./types";

const encoder = new TextEncoder();

export function encodeSseData(obj: unknown): Uint8Array {
  return encoder.encode(`data: ${JSON.stringify(obj)}\n\n`);
}

export function encodeSseDone(): Uint8Array {
  return encoder.encode("data: [DONE]\n\n");
}

export function streamingHeaders(requestId: string): HeadersInit {
  return {
    "content-type": "text/event-stream; charset=utf-8",
    "cache-control": "no-cache, no-transform",
    connection: "keep-alive",
    "x-request-id": requestId,
    "x-accel-buffering": "no",
  };
}

export function jsonHeaders(requestId: string): HeadersInit {
  return {
    "content-type": "application/json; charset=utf-8",
    "x-request-id": requestId,
  };
}

/** Build a synthetic content-delta chunk. */
export function contentChunk(opts: {
  id: string;
  model: string;
  created: number;
  content: string;
  index?: number;
}): ChatCompletionChunk {
  return {
    id: opts.id,
    object: "chat.completion.chunk",
    created: opts.created,
    model: opts.model,
    choices: [
      {
        index: opts.index ?? 0,
        delta: { content: opts.content },
        finish_reason: null,
      },
    ],
  };
}

export function roleChunk(opts: {
  id: string;
  model: string;
  created: number;
}): ChatCompletionChunk {
  return {
    id: opts.id,
    object: "chat.completion.chunk",
    created: opts.created,
    model: opts.model,
    choices: [
      {
        index: 0,
        delta: { role: "assistant", content: "" },
        finish_reason: null,
      },
    ],
  };
}

export function finishChunk(opts: {
  id: string;
  model: string;
  created: number;
  finish_reason?: string;
  usage?: ChatCompletionUsage | null;
}): ChatCompletionChunk {
  return {
    id: opts.id,
    object: "chat.completion.chunk",
    created: opts.created,
    model: opts.model,
    choices: [
      {
        index: 0,
        delta: {},
        finish_reason: opts.finish_reason ?? "stop",
      },
    ],
    usage: opts.usage ?? null,
  };
}

/**
 * Convert a non-streaming CompleteResult into an SSE ReadableStream
 * (useful when upstream adapter lacks native streaming).
 */
export function synthesizeSseFromText(opts: {
  id: string;
  model: string;
  created: number;
  content: string;
  finish_reason?: string | null;
  usage?: ChatCompletionUsage;
  /** Approximate token chunk size for fake streaming */
  chunkChars?: number;
}): ReadableStream<Uint8Array> {
  const chunkChars = opts.chunkChars ?? 24;
  const parts: string[] = [];
  for (let i = 0; i < opts.content.length; i += chunkChars) {
    parts.push(opts.content.slice(i, i + chunkChars));
  }
  if (parts.length === 0) parts.push("");

  let i = 0;
  return new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(
        encodeSseData(
          roleChunk({ id: opts.id, model: opts.model, created: opts.created }),
        ),
      );
    },
    pull(controller) {
      if (i < parts.length) {
        controller.enqueue(
          encodeSseData(
            contentChunk({
              id: opts.id,
              model: opts.model,
              created: opts.created,
              content: parts[i],
            }),
          ),
        );
        i++;
        return;
      }
      controller.enqueue(
        encodeSseData(
          finishChunk({
            id: opts.id,
            model: opts.model,
            created: opts.created,
            finish_reason: opts.finish_reason ?? "stop",
            usage: opts.usage,
          }),
        ),
      );
      controller.enqueue(encodeSseDone());
      controller.close();
    },
  });
}

/**
 * Proxy/normalize an upstream OpenAI-compatible SSE body.
 * - Ensures final `data: [DONE]`
 * - Passes through already-framed SSE with minimal buffering (line-based)
 * - Does not log payloads
 */
export function normalizeUpstreamSse(
  upstream: ReadableStream<Uint8Array>,
  opts?: { signal?: AbortSignal },
): ReadableStream<Uint8Array> {
  const decoder = new TextDecoder();
  let buffer = "";
  let sawDone = false;
  const reader = upstream.getReader();

  return new ReadableStream<Uint8Array>({
    async cancel(reason) {
      try {
        await reader.cancel(reason);
      } catch {
        /* ignore */
      }
    },
    async pull(controller) {
      if (opts?.signal?.aborted) {
        try {
          await reader.cancel("aborted");
        } catch {
          /* ignore */
        }
        controller.close();
        return;
      }
      const { done, value } = await reader.read();
      if (done) {
        if (buffer.trim().length) {
          // flush incomplete line as-is if it looks like SSE
          controller.enqueue(encoder.encode(buffer.endsWith("\n") ? buffer : buffer + "\n\n"));
          buffer = "";
        }
        if (!sawDone) controller.enqueue(encodeSseDone());
        controller.close();
        return;
      }
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      let out = "";
      for (const line of lines) {
        if (line.startsWith("data:")) {
          const payload = line.slice(5).trimStart();
          if (payload === "[DONE]") sawDone = true;
        }
        out += line + "\n";
      }
      if (out) controller.enqueue(encoder.encode(out));
    },
  });
}
