#!/usr/bin/env bash
# // SLOT w08 — expand with more examples
set -euo pipefail
BASE="${GATEWAY_URL:-http://localhost:8787}"
TOKEN="${GATEWAY_TOKEN:-${ADMIN_TOKEN:-}}"

if [[ -z "$TOKEN" ]]; then
  echo "Set GATEWAY_TOKEN or ADMIN_TOKEN" >&2
  exit 1
fi

echo "== health =="
curl -sS "$BASE/health" | jq .

echo "== route map =="
curl -sS "$BASE/v1" -H "Authorization: Bearer $TOKEN" | jq .

echo "== chat =="
curl -sS "$BASE/v1/chat/completions" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-6-luna-free","messages":[{"role":"user","content":"Say hello in one short sentence."}]}' \
  | jq .

echo "== providers (admin) =="
curl -sS "$BASE/admin/providers" -H "Authorization: Bearer $TOKEN" | jq .
