# Provider slice (w02)

## Files

| Path | Role |
|------|------|
| `src/providers/types.ts` | `LLMProvider`, `CompleteParams`, `CompleteResult`, messages |
| `src/providers/openai-compatible.ts` | Generic OpenAI `/chat/completions` adapter |
| `src/providers/apmix.ts` | apmix defaults (`https://api.apmix.ai/v1`, `gpt-6-luna-free`) |
| `src/providers/registry.ts` | `createProvidersFromEnv` / `ProviderRegistry` |
| `src/providers/errors.ts` | `ProviderError`, auth/rate-limit mapping + secret redaction |
| `src/providers/sse.ts` | SSE parser helpers |
| `src/providers/normalize.ts` | Normalize OpenAI JSON → `CompleteResult` |
| `src/providers/url-guard.ts` | https-only SSRF guard for `baseUrl` |
| `src/providers/retry.ts` | Optional retry helper |

## Contract

```ts
complete({ model, messages, stream? })
// stream false → CompleteResult
// stream true  → ReadableStream<Uint8Array> (OpenAI SSE bytes)
completeStream(params) // same as stream:true
```

## Env

- `APMIX_API_KEY` (+ optional `APMIX_BASE_URL`)
- `OPENAI_API_KEY` (+ optional `OPENAI_BASE_URL`)
- `CUSTOM_BASE_URL` + `CUSTOM_API_KEY` → provider id `custom`
- `GATEWAY_DEFAULT_PROVIDER` / `GATEWAY_DEFAULT_MODEL` (consumed by gateway)

## Usage

```ts
import { createProvidersFromEnv } from "./providers";

const registry = createProvidersFromEnv(env);
const provider = registry.resolve(undefined, env.GATEWAY_DEFAULT_PROVIDER ?? "apmix");
const result = await provider.complete({
  model: env.GATEWAY_DEFAULT_MODEL ?? "gpt-6-luna-free",
  messages: [{ role: "user", content: "hi" }],
});
```

w03 owns Anthropic + additional custom styles; this slice already registers a basic OpenAI-compatible `custom` when both custom env vars are set.
