/**
 * Auth middleware helpers (scaffold + w04/w07).
 */

import type { Env } from "../env";
import { extractBearerToken } from "../gateway/auth";
import { lookupBySecret } from "../admin";

export function extractBearer(request: Request): string | null {
  return extractBearerToken(request);
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

export async function requireApiKey(
  request: Request,
  env: Env,
): Promise<Response | null> {
  const token = extractBearer(request);
  if (!token) {
    return jsonError(401, "Missing Authorization Bearer token", "unauthorized");
  }
  if (env.ADMIN_TOKEN && token === env.ADMIN_TOKEN) {
    return null;
  }
  try {
    const rec = await lookupBySecret(env.API_KEYS, token);
    if (!rec || rec.revokedAt) {
      return jsonError(401, "Invalid API key", "unauthorized");
    }
    return null;
  } catch {
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
