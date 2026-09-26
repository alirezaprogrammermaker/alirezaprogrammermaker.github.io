/**
 * Public exports for open-agent-gateway providers (w02).
 */

export * from "./types";
export * from "./errors";
export * from "./sse";
export * from "./normalize";
export * from "./url-guard";
export * from "./retry";
export {
  OpenAICompatibleProvider,
  createOpenAICompatibleProvider,
} from "./openai-compatible";
export {
  ApmixProvider,
  createApmixProvider,
  createOpenAIProvider,
  APMIX_DEFAULT_BASE_URL,
  APMIX_DEFAULT_MODEL,
} from "./apmix";
export {
  ProviderRegistry,
  createProvidersFromEnv,
  createProviderFromEnv,
  type ProviderEnv,
} from "./registry";

/** w03 Anthropic-style + custom baseURL (separate type surface) */
export * as anthropicStyle from "./anthropic-style";
