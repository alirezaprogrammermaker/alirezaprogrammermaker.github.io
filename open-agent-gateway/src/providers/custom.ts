/**
 * // SLOT w03 — Generic OpenAI-compatible custom baseURL adapter
 */

import type { Env } from "../env";
import type { CompleteRequest, CompleteResult, ProviderAdapter } from "./types";

export function createCustomProvider(env: Env): ProviderAdapter {
  return {
    id: "custom",
    async complete(_req: CompleteRequest): Promise<CompleteResult> {
      void env.CUSTOM_BASE_URL;
      void env.CUSTOM_API_KEY;
      // SLOT w03: POST {CUSTOM_BASE_URL}/chat/completions
      throw new Error("SLOT w03: Custom baseURL provider not implemented yet");
    },
  };
}
