/**
 * Parse OpenAI-style SSE from a ReadableStream into chat.completion.chunk objects.
 */

import type { StreamChunk } from "./types";

export async function* parseOpenAISseStream(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<StreamChunk, void, undefined> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let sep: number;
      while ((sep = buffer.indexOf("\n")) >= 0) {
        let line = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 1);
        if (line.endsWith("\r")) line = line.slice(0, -1);
        if (!line || line.startsWith(":")) continue;
        if (!line.startsWith("data:")) continue;
        const data = line.slice(5).trimStart();
        if (data === "[DONE]") return;
        try {
          yield JSON.parse(data) as StreamChunk;
        } catch {
          // skip malformed partial frames
        }
      }
    }
    // flush trailing data line without newline
    const trimmed = buffer.trim();
    if (trimmed.startsWith("data:")) {
      const data = trimmed.slice(5).trimStart();
      if (data && data !== "[DONE]") {
        try {
          yield JSON.parse(data) as StreamChunk;
        } catch {
          /* ignore */
        }
      }
    }
  } finally {
    try {
      reader.releaseLock();
    } catch {
      /* ignore */
    }
  }
}

/** Re-encode parsed chunks (or passthrough upstream bytes) helpers. */
export function encodeSseChunk(obj: unknown): Uint8Array {
  return new TextEncoder().encode(`data: ${JSON.stringify(obj)}\n\n`);
}

export function encodeSseDone(): Uint8Array {
  return new TextEncoder().encode("data: [DONE]\n\n");
}
