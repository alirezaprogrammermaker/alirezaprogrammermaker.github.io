/**
 * // SLOT w04 — Gateway auth middleware
 * External apps: Authorization: Bearer <issued_api_key>
 */

import type { Env } from "../env";

export function extractBearer(request: Request): string | null {
  const header = request.headers.get("Authorization");
  if (!header) return null;
  const m = /^Bearer\s+(.+)$/i.exec(header.trim());
  return m?.[1]?.trim() || null;
}

export function jsonError(
  status: number,
  message: string,
  code?: string,
): Response {
  return Response.json(
    { error: { message, type: "gateway_error", code: code ?? "error" } },
    { status },
  );
}

/**
 * Require a valid issued gateway API key.
 * Until w04 lands, ADMIN_TOKEN (if set) is accepted as a bootstrap bypass for local dev.
 */
export async function requireApiKey(
  request: Request,
  env: Env,
): Promise<Response | null> {
  const token = extractBearer(request);
  if (!token) {
    return jsonError(401, "Missing Authorization Bearer token", "unauthorized");
  }

  // Bootstrap: allow ADMIN_TOKEN while key store is unfinished
  if (env.ADMIN_TOKEN && token === env.ADMIN_TOKEN) {
    return null;
  }

  // SLOT w04: await verifyApiKey(env.API_KEYS, token)
  try {
    const { verifyApiKey } = await import("./keys");
    await verifyApiKey(env.API_KEYS, token);
    return null;
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (msg.includes("SLOT w04")) {
      return jsonError(
        501,
        "API key verification not implemented (SLOT w04). Set ADMIN_TOKEN for bootstrap.",
        "not_implemented",
      );
    }
    return jsonError(401, "Invalid API key", "unauthorized");
  }
}

export async function requireAdmin(
  request: Request,
  env: Env,
): Promise<Response | null> {
  const token = extractBearer(request);
  if (!env.ADMIN_TOKEN) {
    return jsonError(503, "ADMIN_TOKEN secret not configured", "misconfigured");
  }
  if (!token || token !== env.ADMIN_TOKEN) {
    return jsonError(401, "Invalid admin token", "unauthorized");
  }
  return null;
}
