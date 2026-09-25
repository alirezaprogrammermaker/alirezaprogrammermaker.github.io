# Admin HTTP API (w07)

Admin routes manage issued gateway API keys and list pluggable LLM providers.
They require `Authorization: Bearer <ADMIN_TOKEN>` (separate from user API keys).

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/admin/keys` | Create key — returns plaintext **once** |
| `GET` | `/admin/keys` | List keys (prefix + metadata only) |
| `GET` | `/admin/keys/:id` | Get one key (no hash/plaintext) |
| `DELETE` | `/admin/keys/:id` | Revoke key (deletes hash lookup) |
| `GET` | `/admin/providers` | List providers (no upstream secrets) |

## Create body

```json
{
  "name": "mobile-app",
  "scopes": ["chat:completions"],
  "expiresAt": null
}
```

## curl examples

```bash
# Create
curl -sS -X POST "$BASE/admin/keys" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"mobile-app","scopes":["chat:completions"]}'

# List
curl -sS "$BASE/admin/keys" -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# Revoke
curl -sS -X DELETE "$BASE/admin/keys/KEY_ID" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# Providers
curl -sS "$BASE/admin/providers" -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

## Storage

Hashed secrets only in KV:

- `meta:key:{id}` — record JSON
- `lookup:hash:{sha256}` — id
- `index:keys` — id list

## Bindings

- `ADMIN_TOKEN` (secret)
- `API_KEYS` (KV)
- `PROVIDER_REGISTRY` (optional JSON)
- `ADMIN_CORS_ORIGIN` (optional; CORS off by default)
