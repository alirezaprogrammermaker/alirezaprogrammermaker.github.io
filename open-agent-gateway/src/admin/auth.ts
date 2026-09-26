/**
 * Admin Bearer auth (w07).
 * Uses constant-time compare via SHA-256 digests so token length differences
 * do not short-circuit on the first mismatch.
 */

function timingSafeEqualBytes(a: Uint8Array, b: Uint8Array): boolean {
  if (a.byteLength !== b.byteLength) return false;
  let diff = 0;
  for (let i = 0; i < a.byteLength; i++) diff |= a[i]! ^ b[i]!;
  return diff === 0;
}

async function sha256Bytes(input: string): Promise<Uint8Array> {
  const data = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return new Uint8Array(digest);
}

export async function extractBearer(request: Request): Promise<string | null> {
  const header = request.headers.get("Authorization");
  if (!header) return null;
  const m = /^Bearer\s+(.+)$/i.exec(header.trim());
  return m?.[1]?.trim() || null;
}

/**
 * @returns null if authorized; otherwise a 401 Response.
 */
export async function requireAdmin(
  request: Request,
  adminToken: string | undefined,
): Promise<Response | null> {
  if (!adminToken) {
    return new Response(
      JSON.stringify({
        error: { code: "admin_misconfigured", message: "ADMIN_TOKEN is not configured" },
      }),
      { status: 500, headers: { "Content-Type": "application/json; charset=utf-8" } },
    );
  }

  const presented = await extractBearer(request);
  if (!presented) {
    return new Response(
      JSON.stringify({
        error: { code: "unauthorized", message: "Missing Authorization Bearer token" },
      }),
      {
        status: 401,
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "WWW-Authenticate": 'Bearer realm="admin"',
        },
      },
    );
  }

  const [a, b] = await Promise.all([sha256Bytes(presented), sha256Bytes(adminToken)]);
  if (!timingSafeEqualBytes(a, b)) {
    return new Response(
      JSON.stringify({
        error: { code: "unauthorized", message: "Invalid admin token" },
      }),
      {
        status: 401,
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "WWW-Authenticate": 'Bearer realm="admin"',
        },
      },
    );
  }

  return null;
}
