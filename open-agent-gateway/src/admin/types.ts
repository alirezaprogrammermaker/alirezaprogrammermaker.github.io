/** Admin + API-key types for open-agent-gateway (w07). */

export type KeyScope = "chat:completions" | "admin:read" | "admin:write" | string;

export interface ApiKeyRecord {
  id: string;
  name: string;
  /** SHA-256 hex of the full secret. Never expose via HTTP. */
  keyHash: string;
  /** Short non-secret prefix for display, e.g. `oag_a1b2c3d4`. */
  keyPrefix: string;
  createdAt: string;
  revokedAt: string | null;
  scopes: KeyScope[];
  expiresAt?: string | null;
}

/** Safe view returned by list/get (no hash, no plaintext). */
export interface ApiKeyPublic {
  id: string;
  name: string;
  keyPrefix: string;
  createdAt: string;
  revokedAt: string | null;
  scopes: KeyScope[];
  expiresAt?: string | null;
  status: "active" | "revoked" | "expired";
}

/** Returned only once from POST /admin/keys. */
export interface ApiKeyCreated extends ApiKeyPublic {
  /** Full secret — show once; never store plaintext. */
  key: string;
}

export type ProviderKind = "openai-compatible" | "anthropic" | "custom";

export interface ProviderInfo {
  id: string;
  name: string;
  kind: ProviderKind;
  adapter: ProviderKind;
  enabled: boolean;
  /** Public hint only — never include upstream API keys. */
  baseUrlHint?: string;
  models?: string[];
}

export interface AdminEnv {
  ADMIN_TOKEN: string;
  /** Optional; when set, Access-Control-Allow-Origin for /admin. */
  ADMIN_CORS_ORIGIN?: string;
  /** Optional JSON array of ProviderInfo overrides. */
  PROVIDER_REGISTRY?: string;
  /** KV namespace for hashed API keys (shared with w04). */
  API_KEYS: KVNamespace;
}

export interface JsonErrorBody {
  error: {
    code: string;
    message: string;
  };
}
