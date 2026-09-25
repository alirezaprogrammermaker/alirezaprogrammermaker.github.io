/**
 * apmix.ai adapter — OpenAI-compatible upstream with apmix defaults.
 * Base: https://api.apmix.ai/v1  Model: gpt-6-luna-free (free tier)
 */

import { OpenAICompatibleProvider } from "./openai-compatible";
import type { ProviderConfig } from "./types";

export const APMIX_DEFAULT_BASE_URL = "https://api.apmix.ai/v1";
export const APMIX_DEFAULT_MODEL = "gpt-6-luna-free";

export interface ApmixOptions {
  apiKey: string;
  baseUrl?: string;
  defaultHeaders?: Record<string, string>;
  allowPrivateBaseUrl?: boolean;
  fetch?: typeof fetch;
  defaultModel?: string;
}

export class ApmixProvider extends OpenAICompatibleProvider {
  readonly defaultModel: string;

  constructor(opts: ApmixOptions) {
    const config: ProviderConfig = {
      id: "apmix",
      baseUrl: opts.baseUrl ?? APMIX_DEFAULT_BASE_URL,
      apiKey: opts.apiKey,
      defaultHeaders: opts.defaultHeaders,
      allowPrivateBaseUrl: opts.allowPrivateBaseUrl,
      fetch: opts.fetch,
      defaultModel: opts.defaultModel ?? APMIX_DEFAULT_MODEL,
      chatPath: "/chat/completions",
    };
    super(config);
    this.defaultModel = config.defaultModel ?? APMIX_DEFAULT_MODEL;
  }
}

export function createApmixProvider(
  apiKey: string,
  opts: Omit<ApmixOptions, "apiKey"> = {},
): ApmixProvider {
  return new ApmixProvider({ apiKey, ...opts });
}

/** Convenience: OpenAI official API via same compatible adapter. */
export function createOpenAIProvider(
  apiKey: string,
  opts: { baseUrl?: string; fetch?: typeof fetch } = {},
): OpenAICompatibleProvider {
  return new OpenAICompatibleProvider({
    id: "openai",
    baseUrl: opts.baseUrl ?? "https://api.openai.com/v1",
    apiKey,
    fetch: opts.fetch,
  });
}
