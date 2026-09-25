export type {
  AuthHeaderMode,
  ChatMessage,
  ChatRole,
  CompleteRequest,
  CompleteResponse,
  Provider,
  RequestStyle,
  TokenUsage,
} from "./types";

export { ProviderError, readErrorBody, throwProviderHttpError } from "./errors";

export {
  extractTextFromAnthropicContent,
  mapAnthropicUsage,
  mapOpenAIMessagesToAnthropic,
} from "./anthropic-map";
export type {
  AnthropicContentBlock,
  AnthropicMessage,
  AnthropicMessagesInput,
} from "./anthropic-map";

export {
  AnthropicProvider,
  createAnthropicProvider,
} from "./anthropic";
export type { AnthropicProviderConfig } from "./anthropic";

export {
  CustomBaseURLProvider,
  createCustomBaseURLProvider,
} from "./custom";
export type { CustomBaseURLProviderConfig } from "./custom";

export {
  createW03Providers,
  indexProvidersById,
} from "./registry";
export type { ProviderEnv } from "./registry";
