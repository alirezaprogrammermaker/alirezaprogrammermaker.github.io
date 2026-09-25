/**
 * // SLOT w08 — minimal TypeScript client for the gateway
 */

export interface GatewayClientOptions {
  baseUrl: string;
  apiKey: string;
}

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export async function chatCompletions(
  opts: GatewayClientOptions,
  body: {
    model?: string;
    messages: ChatMessage[];
    provider?: string;
    temperature?: number;
  },
): Promise<unknown> {
  const res = await fetch(`${opts.baseUrl.replace(/\/$/, "")}/v1/chat/completions`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${opts.apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`gateway ${res.status}: ${text.slice(0, 300)}`);
  }
  return res.json();
}

// Example (run under a bundler / tsx once deps installed):
// const out = await chatCompletions(
//   { baseUrl: "http://localhost:8787", apiKey: process.env.ADMIN_TOKEN! },
//   { messages: [{ role: "user", content: "hi" }] },
// );
// console.log(out);
