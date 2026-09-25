/**
 * Provider registry + env factory.
 */

import { createApmixProvider, createOpenAIProvider } from "./apmix";
import { ProviderError } from "./errors";
import { createOpenAICompatibleProvider } from "./openai-compatible";
import type { LLMProvider, ProviderId } from "./types";

export interface ProviderEnv {
  APMIX_API_KEY?: string;
  APMIX_BASE_URL?: string;
  OPENAI_API_KEY?: string;
  OPENAI_BASE_URL?: string;
  CUSTOM_BASE_URL?: string;
  CUSTOM_API_KEY?: string;
  GATEWAY_DEFAULT_PROVIDER?: string;
  GATEWAY_DEFAULT_MODEL?: string;
}

export class ProviderRegistry {
  private readonly map = new Map<string, LLMProvider>();

  register(provider: LLMProvider): this {
    this.map.set(String(provider.id), provider);
    return this;
  }

  get(id: ProviderId): LLMProvider {
    const p = this.map.get(String(id));
    if (!p) {
      throw new ProviderError(`Unknown provider: ${id}`, { code: "config" });
    }
    return p;
  }

  has(id: ProviderId): boolean {
    return this.map.has(String(id));
  }

  list(): ProviderId[] {
    return [...this.map.keys()];
  }

  /** Resolve by id or fall back to default when configured. */
  resolve(id?: string | null, fallback?: string): LLMProvider {
    const key = id || fallback;
    if (!key) {
      throw new ProviderError("No provider id specified", { code: "config" });
    }
    return this.get(key);
  }
}

/**
 * Build registry from Worker env secrets/vars.
 * Registers `apmix` and/or `openai` and optional `custom` OpenAI-compatible upstream.
 */
export function createProvidersFromEnv(env: ProviderEnv): ProviderRegistry {
  const registry = new ProviderRegistry();

  if (env.APMIX_API_KEY) {
    registry.register(
      createApmixProvider(env.APMIX_API_KEY, {
        baseUrl: env.APMIX_BASE_URL,
      }),
    );
  }

  if (env.OPENAI_API_KEY) {
    registry.register(
      createOpenAIProvider(env.OPENAI_API_KEY, {
        baseUrl: env.OPENAI_BASE_URL,
      }),
    );
  }

  if (env.CUSTOM_BASE_URL && env.CUSTOM_API_KEY) {
    registry.register(
      createOpenAICompatibleProvider({
        id: "custom",
        baseUrl: env.CUSTOM_BASE_URL,
        apiKey: env.CUSTOM_API_KEY,
      }),
    );
  }

  return registry;
}

/** Alias */
export const createProviderFromEnv = createProvidersFromEnv;
