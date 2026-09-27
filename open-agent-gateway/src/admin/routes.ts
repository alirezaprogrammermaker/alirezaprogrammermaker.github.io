/**
 * Admin HTTP routes (w07):
 *   POST   /admin/keys          — create key (plaintext once)
 *   GET    /admin/keys          — list keys (prefix only)
 *   GET    /admin/keys/:id      — get one key (prefix only)
 *   DELETE /admin/keys/:id      — revoke key
 *   GET    /admin/providers     — list configured providers
 *
 * Auth: Authorization: Bearer <ADMIN_TOKEN>
 * Gateway user keys use /v1/* via w04 — not these routes.
 */

import type { AdminEnv, ApiKeyCreated, KeyScope } from "./types";
import { requireAdmin } from "./auth";
import { jsonErr, jsonOk } from "./http";
import {
  KeyValidationError,
  createApiKey,
  getApiKey,
  listApiKeys,
  revokeApiKey,
  toPublic,
} from "./keys";
import { listProviders } from "./providers";

function corsHeaders(env: AdminEnv): HeadersInit {
  const origin = env.ADMIN_CORS_ORIGIN?.trim();
  if (!origin) return {};
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
    Vary: "Origin",
  };
}

function withCors(env: AdminEnv, res: Response): Response {
  const extra = corsHeaders(env);
  if (!Object.keys(extra).length) return res;
  const headers = new Headers(res.headers);
  for (const [k, v] of Object.entries(extra)) headers.set(k, v as string);
  return new Response(res.body, { status: res.status, headers });
}

function matchAdminPath(pathname: string): {
  resource: "keys" | "providers" | null;
  id?: string;
} {
  const parts = pathname.replace(/\/+$/, "").split("/").filter(Boolean);
  // ["admin", "keys"] | ["admin", "keys", ":id"] | ["admin", "providers"]
  if (parts[0] !== "admin") return { resource: null };
  if (parts[1] === "providers" && parts.length === 2) return { resource: "providers" };
  if (parts[1] === "keys" && parts.length === 2) return { resource: "keys" };
  if (parts[1] === "keys" && parts.length === 3 && parts[2]) {
    return { resource: "keys", id: decodeURIComponent(parts[2]) };
  }
  return { resource: null };
}

async function parseCreateBody(
  request: Request,
): Promise<{ name: string; scopes?: KeyScope[]; expiresAt?: string | null }> {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    throw new KeyValidationError("Request body must be JSON");
  }
  if (!body || typeof body !== "object") {
    throw new KeyValidationError("Request body must be an object");
  }
  const obj = body as Record<string, unknown>;
  if (typeof obj.name !== "string") {
    throw new KeyValidationError("name is required (string)");
  }
  let scopes: KeyScope[] | undefined;
  if (obj.scopes !== undefined) {
    if (!Array.isArray(obj.scopes) || !obj.scopes.every((s) => typeof s === "string")) {
      throw new KeyValidationError("scopes must be an array of strings");
    }
    scopes = obj.scopes as KeyScope[];
  }
  let expiresAt: string | null | undefined;
  if (obj.expiresAt !== undefined) {
    if (obj.expiresAt !== null && typeof obj.expiresAt !== "string") {
      throw new KeyValidationError("expiresAt must be an ISO string or null");
    }
    expiresAt = obj.expiresAt as string | null;
  }
  return { name: obj.name, scopes, expiresAt };
}

/**
 * Handle /admin/* requests.
 * @returns Response, or null if the path is not an admin route.
 */
export async function handleAdminRequest(
  request: Request,
  env: AdminEnv,
): Promise<Response | null> {
  const url = new URL(request.url);
  const matched = matchAdminPath(url.pathname);
  if (!matched.resource) return null;

  if (request.method === "OPTIONS") {
    return withCors(env, new Response(null, { status: 204, headers: corsHeaders(env) }));
  }

  const denied = await requireAdmin(request, env.ADMIN_TOKEN);
  if (denied) return withCors(env, denied);

  if (!env.API_KEYS) {
    return withCors(
      env,
      jsonErr("admin_misconfigured", "API_KEYS KV binding is required", 500),
    );
  }

  try {
    if (matched.resource === "providers") {
      if (request.method !== "GET") {
        return withCors(env, jsonErr("method_not_allowed", "Use GET", 405));
      }
      return withCors(env, jsonOk({ providers: listProviders(env) }));
    }

    // keys
    if (!matched.id) {
      if (request.method === "GET") {
        const keys = await listApiKeys(env.API_KEYS);
        return withCors(env, jsonOk({ keys }));
      }
      if (request.method === "POST") {
        const input = await parseCreateBody(request);
        const { record, plaintext } = await createApiKey(env.API_KEYS, input);
        const created: ApiKeyCreated = {
          ...toPublic(record),
          key: plaintext,
        };
        return withCors(env, jsonOk(created, 201));
      }
      return withCors(env, jsonErr("method_not_allowed", "Use GET or POST", 405));
    }

    if (request.method === "GET") {
      const rec = await getApiKey(env.API_KEYS, matched.id);
      if (!rec) return withCors(env, jsonErr("not_found", "API key not found", 404));
      return withCors(env, jsonOk({ key: toPublic(rec) }));
    }

    if (request.method === "DELETE") {
      const result = await revokeApiKey(env.API_KEYS, matched.id);
      if (!result.ok) return withCors(env, jsonErr("not_found", "API key not found", 404));
      return withCors(
        env,
        jsonOk({
          revoked: true,
          key: toPublic(result.record),
        }),
      );
    }

    return withCors(env, jsonErr("method_not_allowed", "Use GET or DELETE", 405));
  } catch (err) {
    if (err instanceof KeyValidationError) {
      return withCors(env, jsonErr("bad_request", err.message, 400));
    }
    console.error("admin route error");
    return withCors(env, jsonErr("internal_error", "Unexpected admin error", 500));
  }
}

/** Thin fetch wrapper for mounting from the Worker entry. */
export async function adminFetch(request: Request, env: AdminEnv): Promise<Response> {
  const res = await handleAdminRequest(request, env);
  if (res) return res;
  return jsonErr("not_found", "Unknown admin route", 404);
}
