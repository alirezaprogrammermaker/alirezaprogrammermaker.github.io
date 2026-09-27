import type { AdminEnv, ProviderInfo } from "./types";

/** Built-in registry — no upstream secrets. */
export const DEFAULT_PROVIDERS: ProviderInfo[] = [
  {
    id: "openai",
    name: "OpenAI-compatible",
    kind: "openai-compatible",
    adapter: "openai-compatible",
    enabled: true,
    baseUrlHint: "https://api.openai.com/v1",
    models: ["gpt-4o", "gpt-4o-mini"],
  },
  {
    id: "anthropic",
    name: "Anthropic",
    kind: "anthropic",
    adapter: "anthropic",
    enabled: true,
    baseUrlHint: "https://api.anthropic.com",
    models: ["claude-sonnet-4-5", "claude-haiku-4-5"],
  },
  {
    id: "apmix",
    name: "apmix",
    kind: "openai-compatible",
    adapter: "openai-compatible",
    enabled: true,
    baseUrlHint: "https://api.apmix.ai/v1",
    models: ["gpt-6-luna-free"],
  },
  {
    id: "custom",
    name: "Custom base URL",
    kind: "custom",
    adapter: "custom",
    enabled: true,
    baseUrlHint: "https://example.com/v1",
    models: [],
  },
];

function sanitizeProvider(p: Partial<ProviderInfo> & { id: string; name: string }): ProviderInfo {
  const kind = (p.kind ?? p.adapter ?? "openai-compatible") as ProviderInfo["kind"];
  return {
    id: p.id,
    name: p.name,
    kind,
    adapter: (p.adapter ?? kind) as ProviderInfo["adapter"],
    enabled: p.enabled !== false,
    baseUrlHint: p.baseUrlHint,
    models: Array.isArray(p.models) ? p.models.map(String) : [],
  };
}

/**
 * List providers for GET /admin/providers.
 * Never includes API keys — only public registry metadata.
 */
export function listProviders(env: Pick<AdminEnv, "PROVIDER_REGISTRY">): ProviderInfo[] {
  const raw = env.PROVIDER_REGISTRY?.trim();
  if (!raw) return DEFAULT_PROVIDERS.map((p) => ({ ...p }));

  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed) || parsed.length === 0) return DEFAULT_PROVIDERS.map((p) => ({ ...p }));

    return parsed
      .filter((x): x is Record<string, unknown> => !!x && typeof x === "object")
      .filter((x) => typeof x.id === "string" && typeof x.name === "string")
      .map((x) =>
        sanitizeProvider({
          id: x.id as string,
          name: x.name as string,
          kind: x.kind as ProviderInfo["kind"] | undefined,
          adapter: x.adapter as ProviderInfo["adapter"] | undefined,
          enabled: x.enabled as boolean | undefined,
          baseUrlHint: typeof x.baseUrlHint === "string" ? x.baseUrlHint : undefined,
          models: Array.isArray(x.models) ? (x.models as string[]) : [],
        }),
      );
  } catch {
    return DEFAULT_PROVIDERS.map((p) => ({ ...p }));
  }
}
