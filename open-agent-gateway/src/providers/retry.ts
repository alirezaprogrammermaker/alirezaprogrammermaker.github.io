/**
 * Lightweight retry for retryable upstream failures.
 */

import { ProviderError, RateLimitError } from "./errors";

export interface RetryOptions {
  retries?: number;
  retryOnStatus?: number[];
  baseDelayMs?: number;
}

export async function withRetry<T>(
  fn: (attempt: number) => Promise<T>,
  opts: RetryOptions = {},
): Promise<T> {
  const retries = opts.retries ?? 2;
  const baseDelayMs = opts.baseDelayMs ?? 400;

  let lastErr: unknown;
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      return await fn(attempt);
    } catch (err) {
      lastErr = err;
      const retryable =
        err instanceof RateLimitError ||
        (err instanceof ProviderError && err.retryable);
      if (!retryable || attempt === retries) throw err;
      let delay = baseDelayMs * 2 ** attempt;
      if (err instanceof RateLimitError && err.retryAfterMs) {
        delay = Math.max(delay, err.retryAfterMs);
      }
      await new Promise((r) => setTimeout(r, delay));
    }
  }
  throw lastErr;
}
