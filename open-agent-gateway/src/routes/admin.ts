/**
 * // SLOT w07 — Admin HTTP routes: create/revoke keys + list providers
 */

import type { Env } from "../env";
import { requireAdmin, jsonError } from "../auth/middleware";
import { listProviders } from "../providers/registry";

export async function handleAdmin(
  request: Request,
  env: Env,
  path: string,
): Promise<Response> {
  const authErr = await requireAdmin(request, env);
  if (authErr) return authErr;

  // GET /admin/providers
  if (path === "/admin/providers" && request.method === "GET") {
    return Response.json({
      providers: listProviders(),
      default: env.GATEWAY_DEFAULT_PROVIDER,
      default_model: env.GATEWAY_DEFAULT_MODEL,
    });
  }

  // POST /admin/keys — SLOT w07 + w04
  if (path === "/admin/keys" && request.method === "POST") {
    return jsonError(
      501,
      "Key issuance not implemented (SLOT w04 / w07)",
      "not_implemented",
    );
  }

  // DELETE /admin/keys/:id — SLOT w07 + w04
  if (path.startsWith("/admin/keys/") && request.method === "DELETE") {
    return jsonError(
      501,
      "Key revoke not implemented (SLOT w04 / w07)",
      "not_implemented",
    );
  }

  // GET /admin/keys — SLOT w07
  if (path === "/admin/keys" && request.method === "GET") {
    return jsonError(
      501,
      "Key list not implemented (SLOT w07)",
      "not_implemented",
    );
  }

  return jsonError(404, "Admin route not found", "not_found");
}
