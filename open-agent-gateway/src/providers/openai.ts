/**
 * // SLOT w02 — OpenAI-compatible adapter (api.openai.com/v1)
 * Stub: returns a clear not-implemented error until w02 lands.
 */

import type { Env } from "../env";
import type { CompleteRequest, CompleteResult, ProviderAdapter } from "./types";

export function createOpenAIProvider(env: Env): ProviderAdapter {
  return {
    id: "openai",
    async complete(_req: CompleteRequest): Promise<CompleteResult> {
      void env.OPENAI_API_KEY;
      // SLOT w02: implement OpenAI chat.completions call
      throw new Error("SLOT w02: OpenAI provider not implemented yet");
    },
  };
}
