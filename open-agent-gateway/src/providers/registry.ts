/**
 * Provider registry — resolve adapters by id.
 * // SLOT w02: register openai + apmix
 * // SLOT w03: register anthropic + custom
 */

import type { Env } from "../env";
import type { ProviderAdapter, ProviderId } from "./types";
import { createOpenAIProvider } from "./openai";
import { createApmixProvider } from "./apmix";
import { createAnthropicProvider } from "./anthropic";
import { createCustomProvider } from "./custom";

export function listProviders(): ProviderId[] {
  return ["openai", "apmix", "anthropic", "custom"];
}

export function resolveProvider(id: ProviderId, env: Env): ProviderAdapter {
  switch (id) {
    case "openai":
      return createOpenAIProvider(env);
    case "apmix":
      return createApmixProvider(env);
    case "anthropic":
      return createAnthropicProvider(env);
    case "custom":
      return createCustomProvider(env);
    default: {
      const _exhaustive: never = id;
      throw new Error(`Unknown provider: ${_exhaustive}`);
    }
  }
}

export function resolveDefaultProvider(env: Env): ProviderAdapter {
  const id = (env.GATEWAY_DEFAULT_PROVIDER || "apmix") as ProviderId;
  if (!listProviders().includes(id)) {
    return createApmixProvider(env);
  }
  return resolveProvider(id, env);
}
