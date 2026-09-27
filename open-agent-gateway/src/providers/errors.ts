/**
 * Provider errors — never embed raw API keys in messages.
 */

export type ProviderErrorCode =
  | "auth"
  | "rate_limit"
  | "invalid_request"
  | "upstream"
  | "network"
  | "parse"
  | "config";

const SECRET_RE =
  /\b(sk-[A-Za-z0-9_-]{8,}|apx_live_[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._\-]+)/gi;

export function redactSecrets(text: string): string {
  return text.replace(SECRET_RE, "[REDACTED]");
}

export class ProviderError extends Error {
  readonly code: ProviderErrorCode;
  readonly status?: number;
  readonly retryable: boolean;
  readonly providerId?: string;
  readonly bodySnippet?: string;

  constructor(
    message: string,
    opts: {
      code: ProviderErrorCode;
      status?: number;
      retryable?: boolean;
      providerId?: string;
      bodySnippet?: string;
      cause?: unknown;
    },
  ) {
    super(redactSecrets(message), { cause: opts.cause });
    this.name = "ProviderError";
    this.code = opts.code;
    this.status = opts.status;
    this.retryable = opts.retryable ?? false;
    this.providerId = opts.providerId;
    this.bodySnippet = opts.bodySnippet
      ? redactSecrets(opts.bodySnippet).slice(0, 400)
      : undefined;
  }
}

export class AuthError extends ProviderError {
  constructor(message = "Upstream authentication failed", opts: Partial<ConstructorParameters<typeof ProviderError>[1]> = {}) {
    super(message, { code: "auth", status: 401, retryable: false, ...opts });
    this.name = "AuthError";
  }
}

export class RateLimitError extends ProviderError {
  readonly retryAfterMs?: number;

  constructor(
    message = "Upstream rate limited",
    opts: Partial<ConstructorParameters<typeof ProviderError>[1]> & { retryAfterMs?: number } = {},
  ) {
    const { retryAfterMs, ...rest } = opts;
    super(message, { code: "rate_limit", status: 429, retryable: true, ...rest });
    this.name = "RateLimitError";
    this.retryAfterMs = retryAfterMs;
  }
}

export class UpstreamError extends ProviderError {
  constructor(
    message: string,
    opts: Partial<ConstructorParameters<typeof ProviderError>[1]> & { status: number },
  ) {
    const status = opts.status;
    const retryable = opts.retryable ?? (status === 408 || status === 425 || status >= 500);
    super(message, { code: "upstream", ...opts, status, retryable });
    this.name = "UpstreamError";
  }
}

export function mapHttpError(
  status: number,
  bodyText: string,
  providerId?: string,
): ProviderError {
  const snippet = bodyText.slice(0, 400);
  if (status === 401 || status === 403) {
    return new AuthError(`Upstream auth failed (${status})`, {
      status,
      providerId,
      bodySnippet: snippet,
    });
  }
  if (status === 429) {
    return new RateLimitError(`Upstream rate limited`, {
      status,
      providerId,
      bodySnippet: snippet,
    });
  }
  if (status === 400 || status === 404 || status === 422) {
    return new ProviderError(`Upstream rejected request (${status})`, {
      code: "invalid_request",
      status,
      providerId,
      bodySnippet: snippet,
    });
  }
  return new UpstreamError(`Upstream error (${status})`, {
    status,
    providerId,
    bodySnippet: snippet,
  });
}
