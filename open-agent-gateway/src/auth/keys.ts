/**
 * // SLOT w04 — API key issuance, hashing, KV storage
 *
 * Contract:
 * - Issue random keys once; store only SHA-256 hash in KV
 * - KV key shape: `key:{keyId}` → JSON { hash, createdAt, revoked?, label? }
 * - Presented token: `oag_{keyId}_{secret}` (or similar) — never log plaintext
 */

export interface ApiKeyRecord {
  hash: string;
  createdAt: string;
  label?: string;
  revoked?: boolean;
  scopes?: string[];
}

export async function hashSecret(secret: string): Promise<string> {
  const data = new TextEncoder().encode(secret);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/** // SLOT w04: implement full issue/revoke/list against env.API_KEYS */
export async function issueApiKey(
  _kv: KVNamespace,
  _label?: string,
): Promise<{ id: string; token: string }> {
  throw new Error("SLOT w04: issueApiKey not implemented yet");
}

export async function revokeApiKey(
  _kv: KVNamespace,
  _id: string,
): Promise<boolean> {
  throw new Error("SLOT w04: revokeApiKey not implemented yet");
}

export async function verifyApiKey(
  _kv: KVNamespace,
  _token: string,
): Promise<ApiKeyRecord | null> {
  // SLOT w04: parse token, load hash from KV, timing-safe compare
  throw new Error("SLOT w04: verifyApiKey not implemented yet");
}
