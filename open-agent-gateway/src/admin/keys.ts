/**
 * KV storage for hashed API keys.
 * Layout (contract with w04 auth middleware):
 *   meta:key:{id}     → ApiKeyRecord JSON
 *   lookup:hash:{hex} → id
 *   index:keys        → string[] of ids
 */

import type { ApiKeyPublic, ApiKeyRecord, KeyScope } from "./types";
import { generateApiKeySecret, hashApiKey, keyPrefixOf, newKeyId } from "./crypto";

const META = (id: string) => `meta:key:${id}`;
const LOOKUP = (hash: string) => `lookup:hash:${hash}`;
const INDEX = "index:keys";

export function toPublic(record: ApiKeyRecord, now = new Date()): ApiKeyPublic {
  let status: ApiKeyPublic["status"] = "active";
  if (record.revokedAt) status = "revoked";
  else if (record.expiresAt && new Date(record.expiresAt) <= now) status = "expired";

  return {
    id: record.id,
    name: record.name,
    keyPrefix: record.keyPrefix,
    createdAt: record.createdAt,
    revokedAt: record.revokedAt,
    scopes: record.scopes,
    expiresAt: record.expiresAt ?? null,
    status,
  };
}

async function readIndex(kv: KVNamespace): Promise<string[]> {
  const raw = await kv.get(INDEX);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

async function writeIndex(kv: KVNamespace, ids: string[]): Promise<void> {
  await kv.put(INDEX, JSON.stringify(ids));
}

export interface CreateKeyInput {
  name: string;
  scopes?: KeyScope[];
  expiresAt?: string | null;
}

export interface CreateKeyResult {
  record: ApiKeyRecord;
  plaintext: string;
}

export async function createApiKey(
  kv: KVNamespace,
  input: CreateKeyInput,
): Promise<CreateKeyResult> {
  const name = input.name.trim();
  if (!name || name.length > 64) {
    throw new KeyValidationError("name must be 1–64 characters");
  }

  const scopes = input.scopes?.length ? input.scopes : (["chat:completions"] as KeyScope[]);
  const plaintext = generateApiKeySecret();
  const keyHash = await hashApiKey(plaintext);
  const id = newKeyId();
  const createdAt = new Date().toISOString();

  const record: ApiKeyRecord = {
    id,
    name,
    keyHash,
    keyPrefix: keyPrefixOf(plaintext),
    createdAt,
    revokedAt: null,
    scopes,
    expiresAt: input.expiresAt ?? null,
  };

  const ids = await readIndex(kv);
  ids.push(id);

  await Promise.all([
    kv.put(META(id), JSON.stringify(record)),
    kv.put(LOOKUP(keyHash), id),
    writeIndex(kv, ids),
  ]);

  return { record, plaintext };
}

export async function getApiKey(kv: KVNamespace, id: string): Promise<ApiKeyRecord | null> {
  const raw = await kv.get(META(id));
  if (!raw) return null;
  try {
    return JSON.parse(raw) as ApiKeyRecord;
  } catch {
    return null;
  }
}

export async function listApiKeys(kv: KVNamespace): Promise<ApiKeyPublic[]> {
  const ids = await readIndex(kv);
  const out: ApiKeyPublic[] = [];
  for (const id of ids) {
    const rec = await getApiKey(kv, id);
    if (rec) out.push(toPublic(rec));
  }
  // Newest first
  out.sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1));
  return out;
}

/**
 * Revoke by id. Idempotent: already-revoked returns the record.
 * Deletes hash lookup so bearer auth fails immediately.
 */
export async function revokeApiKey(
  kv: KVNamespace,
  id: string,
): Promise<{ ok: true; record: ApiKeyRecord } | { ok: false; reason: "not_found" }> {
  const rec = await getApiKey(kv, id);
  if (!rec) return { ok: false, reason: "not_found" };

  if (!rec.revokedAt) {
    rec.revokedAt = new Date().toISOString();
    await Promise.all([kv.put(META(id), JSON.stringify(rec)), kv.delete(LOOKUP(rec.keyHash))]);
  }

  return { ok: true, record: rec };
}

/** Resolve a presented bearer secret to a non-revoked record (for w04). */
export async function lookupBySecret(
  kv: KVNamespace,
  secret: string,
): Promise<ApiKeyRecord | null> {
  const hash = await hashApiKey(secret);
  const id = await kv.get(LOOKUP(hash));
  if (!id) return null;
  const rec = await getApiKey(kv, id);
  if (!rec || rec.revokedAt) return null;
  if (rec.expiresAt && new Date(rec.expiresAt) <= new Date()) return null;
  return rec;
}

export class KeyValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "KeyValidationError";
  }
}
