import type { JsonErrorBody } from "./types";

const JSON_HEADERS = { "Content-Type": "application/json; charset=utf-8" };

export function jsonOk<T>(data: T, status = 200, extraHeaders?: HeadersInit): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...JSON_HEADERS, ...extraHeaders },
  });
}

export function jsonErr(
  code: string,
  message: string,
  status: number,
  extraHeaders?: HeadersInit,
): Response {
  const body: JsonErrorBody = { error: { code, message } };
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...JSON_HEADERS, ...extraHeaders },
  });
}

/** Mask secrets in log lines — never print full Bearer / oag_ keys. */
export function redact(value: string): string {
  return value
    .replace(/Bearer\s+[A-Za-z0-9._\-]+/gi, (m) => {
      const token = m.slice(7).trim();
      return `Bearer ${token.slice(0, 8)}…`;
    })
    .replace(/\boag_[A-Za-z0-9_\-]+/g, (m) => `${m.slice(0, 12)}…`);
}
