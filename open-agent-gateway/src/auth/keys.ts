/**
 * Auth stubs — w04 ownership.
 * Production key hashing/issue lives in `src/admin` (w07) + KV.
 * Gateway Bearer verification hook: `src/gateway/auth.ts`.
 */

export {
  hashApiKey as hashSecret,
  createApiKey,
  revokeApiKey,
  lookupBySecret as verifyApiKey,
} from "../admin";

export type { ApiKeyRecord } from "../admin";
