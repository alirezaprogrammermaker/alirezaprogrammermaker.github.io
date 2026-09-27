/**
 * Auth extraction for gateway routes.
 * Real key verification lives in w04; this module only parses Bearer
 * and exposes a hook for the KV/DO authenticator.
 */

import type { GatewayAuthContext, GatewayEnv } from "./types";
import { unauthorized } from "./errors";

export function extractBearerToken(request: Request): string | null {
  const h = request.headers.get("authorization") || request.headers.get("Authorization");
  if (!h) return null;
  const m = /^Bearer\s+(.+)$/i.exec(h.trim());
  if (!m) return null;
  const token = m[1].trim();
  return token.length ? token : null;
}

/**
 * Pluggable authenticator. w04 should replace `authenticateGatewayKey`.
 * Default: require non-empty Bearer; optionally accept UPSTREAM passthrough
 * only for local/dev when env.API_KEYS is unset (still no key logging).
 */
export type Authenticator = (
  request: Request,
  env: GatewayEnv,
) => Promise<GatewayAuthContext | null>;

export const authenticateGatewayKey: Authenticator = async (request, env) => {
  const token = extractBearerToken(request);
  if (!token) return null;

  if (env.API_KEYS) {
    // Expected KV schema (w04): key = sha256(token) hex, value = JSON { keyId, status }
    const digest = await sha256Hex(token);
    const raw = await env.API_KEYS.get(`key:${digest}`);
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw) as { keyId?: string; status?: string; subject?: string };
      if (parsed.status && parsed.status !== "active") return null;
      if (!parsed.keyId) return null;
      return { keyId: parsed.keyId, subject: parsed.subject };
    } catch {
      return null;
    }
  }

  // Dev fallback: any non-empty bearer is accepted as anonymous/dev
  return { keyId: "dev", subject: "dev" };
};

export async function requireAuth(
  request: Request,
  env: GatewayEnv,
  authenticate: Authenticator = authenticateGatewayKey,
): Promise<GatewayAuthContext | Response> {
  const ctx = await authenticate(request, env);
  if (!ctx) return unauthorized();
  return ctx;
}

async function sha256Hex(input: string): Promise<string> {
  const data = new TextEncoder().encode(input);
  const hash = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Safe log fields — never include Authorization or raw tokens. */
export function safeAuthLog(ctx: GatewayAuthContext): Record<string, string> {
  return { keyId: ctx.keyId, subject: ctx.subject ?? "" };
}
