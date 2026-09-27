import { readFileSync } from "node:fs";
import { createApmixProvider } from "../src/providers/apmix";

async function main() {
  const key = readFileSync("/tmp/wt-w02-burn/key.txt", "utf8").trim();
  const p = createApmixProvider(key);
  const r = await p.complete({
    model: "gpt-6-luna-free",
    messages: [{ role: "user", content: "Reply exactly: ADAPTER_OK" }],
    max_tokens: 16,
  });
  console.log("adapter_live", JSON.stringify(r.message.content), "finish", r.finish_reason);
}

main().catch((e) => {
  console.error("adapter_live_fail", e instanceof Error ? e.message : e);
  process.exit(1);
});
