/**
 * // SLOT w02 — apmix OpenAI-compatible adapter (https://api.apmix.ai/v1)
 * Minimal working stub so the scaffold can call apmix when secrets are set.
 */

import type { Env } from "../env";
import type { CompleteRequest, CompleteResult, ProviderAdapter } from "./types";

const APMIX_BASE = "https://api.apmix.ai/v1";

export function createApmixProvider(env: Env): ProviderAdapter {
  return {
    id: "apmix",
    async complete(req: CompleteRequest): Promise<CompleteResult> {
      const apiKey = env.APMIX_API_KEY;
      if (!apiKey) {
        throw new Error("APMIX_API_KEY secret is not configured");
      }

      // SLOT w02: harden streaming, error mapping, retries
      const res = await fetch(`${APMIX_BASE}/chat/completions`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${apiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model: req.model,
          messages: req.messages,
          stream: false,
          temperature: req.temperature,
          max_tokens: req.max_tokens,
        }),
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(`apmix upstream ${res.status}: ${text.slice(0, 200)}`);
      }

      const data = (await res.json()) as {
        choices?: Array<{ message?: { content?: string }; finish_reason?: string }>;
        usage?: {
          prompt_tokens?: number;
          completion_tokens?: number;
          total_tokens?: number;
        };
      };

      return {
        content: data.choices?.[0]?.message?.content ?? "",
        finish_reason: data.choices?.[0]?.finish_reason ?? null,
        usage: data.usage,
        raw: data,
      };
    },
  };
}
