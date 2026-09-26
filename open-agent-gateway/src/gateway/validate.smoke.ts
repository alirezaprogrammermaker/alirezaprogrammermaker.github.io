/**
 * Lightweight pure-function tests for w05 validate/streaming
 * (vitest-ready; w09 can import).
 */

import { normalizeChatCompletionRequest, wantsStream } from "./validate";
import { encodeSseData, encodeSseDone } from "./streaming";

export function runValidateSmoke(): string[] {
  const failures: string[] = [];

  const ok = normalizeChatCompletionRequest({
    model: "gpt-6-luna-free",
    messages: [{ role: "user", content: "hi" }],
  });
  if (!ok.ok) failures.push("expected valid request");

  const missing = normalizeChatCompletionRequest({ messages: [] });
  if (missing.ok || missing.param !== "model") failures.push("expected missing model");

  const emptyMsg = normalizeChatCompletionRequest({
    model: "m",
    messages: [],
  });
  if (emptyMsg.ok) failures.push("expected empty messages fail");

  const streamN = normalizeChatCompletionRequest({
    model: "m",
    messages: [{ role: "user", content: "x" }],
    stream: true,
    n: 2,
  });
  if (streamN.ok) failures.push("expected n>1 stream reject");

  const url = new URL("https://gw.example/v1/chat/completions?stream=true");
  if (!wantsStream({}, url)) failures.push("query stream=true");

  const sse = new TextDecoder().decode(encodeSseData({ a: 1 }));
  if (!sse.startsWith("data: ") || !sse.endsWith("\n\n")) failures.push("sse encode");
  const done = new TextDecoder().decode(encodeSseDone());
  if (done !== "data: [DONE]\n\n") failures.push("sse done");

  return failures;
}
