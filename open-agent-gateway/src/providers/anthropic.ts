/**
 * // SLOT w03 — Anthropic-style Messages API adapter
 */

import type { Env } from "../env";
import type { CompleteRequest, CompleteResult, ProviderAdapter } from "./types";

export function createAnthropicProvider(env: Env): ProviderAdapter {
  return {
    id: "anthropic",
    async complete(_req: CompleteRequest): Promise<CompleteResult> {
      void env.ANTHROPIC_API_KEY;
      // SLOT w03: implement Anthropic messages API
      throw new Error("SLOT w03: Anthropic provider not implemented yet");
    },
  };
}
