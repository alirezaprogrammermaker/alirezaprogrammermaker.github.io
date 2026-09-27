# w05 — Chat completions gateway (curl examples)

Base: `https://<worker>/v1/chat/completions`  
Auth: `Authorization: Bearer <issued_gateway_api_key>`  
Never put provider upstream keys in client requests.

## Non-streaming

```bash
curl -sS https://localhost:8787/v1/chat/completions \
  -H "Authorization: Bearer $GATEWAY_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-6-luna-free",
    "messages": [{"role":"user","content":"Say hi in one word"}],
    "max_tokens": 32
  }'
```

## Streaming (SSE)

```bash
curl -sS -N https://localhost:8787/v1/chat/completions \
  -H "Authorization: Bearer $GATEWAY_KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "model": "gpt-6-luna-free",
    "stream": true,
    "messages": [{"role":"user","content":"Count to 5"}],
    "max_tokens": 64
  }'
```

Expect lines like `data: {"object":"chat.completion.chunk",...}` and a final `data: [DONE]`.

## Errors

Missing auth → `401` OpenAI-shaped `{ "error": { "type": "authentication_error", ... } }`.  
Invalid body → `400` `invalid_request_error`.
