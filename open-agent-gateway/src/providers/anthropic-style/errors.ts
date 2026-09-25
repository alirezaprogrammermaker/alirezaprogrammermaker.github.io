/**
 * Provider errors — no secrets in messages.
 */

export class ProviderError extends Error {
  readonly status?: number;
  readonly code?: string;
  readonly provider: string;

  constructor(
    message: string,
    opts: { status?: number; code?: string; provider: string; cause?: unknown },
  ) {
    super(message);
    this.name = "ProviderError";
    this.status = opts.status;
    this.code = opts.code;
    this.provider = opts.provider;
    if (opts.cause !== undefined) {
      (this as Error & { cause?: unknown }).cause = opts.cause;
    }
  }
}

export async function readErrorBody(res: Response): Promise<string> {
  try {
    const text = await res.text();
    // Truncate and strip likely key-shaped tokens
    return text
      .slice(0, 500)
      .replace(/apx_live_[A-Za-z0-9]+/g, "apx_live_[REDACTED]")
      .replace(/sk-[A-Za-z0-9]+/g, "sk-[REDACTED]")
      .replace(/Bearer\s+\S+/gi, "Bearer [REDACTED]");
  } catch {
    return "";
  }
}

export async function throwProviderHttpError(
  provider: string,
  res: Response,
): Promise<never> {
  const body = await readErrorBody(res);
  let code: string | undefined;
  try {
    const parsed = JSON.parse(body) as {
      error?: { type?: string; code?: string; message?: string };
      type?: string;
    };
    code = parsed.error?.type ?? parsed.error?.code ?? parsed.type;
  } catch {
    /* ignore */
  }
  throw new ProviderError(
    `${provider} HTTP ${res.status}${body ? `: ${body}` : ""}`,
    { status: res.status, code, provider },
  );
}
