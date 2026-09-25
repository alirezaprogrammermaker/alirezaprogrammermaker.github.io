/**
 * // SLOT w09 — Rate-limit stubs (KV or DO counters)
 */

import type { Env } from "../env";

export interface RateLimitResult {
  allowed: boolean;
  remaining: number;
  resetAt: number;
}

/** Stub: always allows. Replace with token-bucket / fixed window in w09. */
export async function checkRateLimit(
  _env: Env,
  _keyId: string,
): Promise<RateLimitResult> {
  // SLOT w09: implement per-key rate limits
  return {
    allowed: true,
    remaining: 999,
    resetAt: Date.now() + 60_000,
  };
}
