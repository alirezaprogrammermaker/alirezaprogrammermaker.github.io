/**
 * Gateway barrel — w05 chat completions slice.
 */

export { handleChatCompletions, isChatCompletionsPath } from "./chat-completions";
export type { ChatCompletionsDeps } from "./chat-completions";
export * from "./types";
export * from "./errors";
export * from "./validate";
export * from "./streaming";
export * from "./auth";
export { createUpstreamOpenAIAdapter, UpstreamHttpError } from "./upstream";
