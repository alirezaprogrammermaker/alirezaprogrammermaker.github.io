/**
 * Example Worker entry mount for admin routes (w07).
 * w01 should merge this into the real `src/index.ts`.
 */
import { handleAdminRequest, type AdminEnv } from "./admin";

export interface Env extends AdminEnv {
  // … other bindings from w01–w06
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const admin = await handleAdminRequest(request, env);
    if (admin) return admin;

    // … /v1/chat/completions (w05), agents (w06), etc.
    return new Response(JSON.stringify({ error: { code: "not_found", message: "Not found" } }), {
      status: 404,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  },
};
