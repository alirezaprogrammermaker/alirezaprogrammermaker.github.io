/**
 * Register Anthropic + custom providers from Worker env bindings.
 */

import { createAnthropicProvider } from "./anthropic";
import { createCustomBaseURLProvider } from "./custom";
import type { Provider } from "./types";

export type ProviderEnv = {
  ANTHROPIC_API_KEY?: string;
  ANTHROPIC_BASE_URL?: string;
  ANTHROPIC_VERSION?: string;
  ANTHROPIC_MAX_TOKENS?: string;
  CUSTOM_LLM_BASE_URL?: string;
  CUSTOM_LLM_API_KEY?: string;
  CUSTOM_LLM_PATH?: string;
  CUSTOM_LLM_AUTH?: string;
  CUSTOM_LLM_STYLE?: string;
  CUSTOM_LLM_EXTRA_HEADERS_JSON?: string;
};

/**
 * Returns providers owned by this slice (anthropic + custom).
 * w02 will merge openai/apmix into the full registry.
 */
export function createW03Providers(env: ProviderEnv): Provider[] {
  const out: Provider[] = [];
  const anthropic = createAnthropicProvider(env);
  if (anthropic) out.push(anthropic);
  const custom = createCustomBaseURLProvider(env);
  if (custom) out.push(custom);
  return out;
}

export function indexProvidersById(providers: Provider[]): Map<string, Provider> {
  return new Map(providers.map((p) => [p.id, p]));
}
