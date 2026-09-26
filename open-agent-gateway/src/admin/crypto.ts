/** Crypto helpers for issued gateway API keys (shared layout with w04). */

const KEY_PREFIX = "oag_";

function bytesToHex(bytes: Uint8Array): string {
  let out = "";
  for (const b of bytes) out += b.toString(16).padStart(2, "0");
  return out;
}

function bytesToBase64Url(bytes: Uint8Array): string {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

/** Generate `oag_` + 32 random bytes (base64url). */
export function generateApiKeySecret(): string {
  const raw = crypto.getRandomValues(new Uint8Array(32));
  return KEY_PREFIX + bytesToBase64Url(raw);
}

export async function hashApiKey(secret: string): Promise<string> {
  const data = new TextEncoder().encode(secret);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return bytesToHex(new Uint8Array(digest));
}

/** Display prefix: `oag_` + first 8 chars of the random portion. */
export function keyPrefixOf(secret: string): string {
  if (secret.startsWith(KEY_PREFIX)) {
    return secret.slice(0, KEY_PREFIX.length + 8);
  }
  return secret.slice(0, 12);
}

export function newKeyId(): string {
  return crypto.randomUUID();
}
