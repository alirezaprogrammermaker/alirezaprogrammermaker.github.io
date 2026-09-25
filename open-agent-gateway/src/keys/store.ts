/**
 * Re-exports for w04 auth middleware — hashed key store helpers.
 * Prefer importing from `../admin` in new code.
 */
export {
  createApiKey,
  getApiKey,
  listApiKeys,
  revokeApiKey,
  lookupBySecret,
  toPublic,
  KeyValidationError,
  hashApiKey,
  generateApiKeySecret,
} from "../admin";
