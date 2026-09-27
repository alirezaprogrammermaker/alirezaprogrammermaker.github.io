import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
    // SLOT w09: switch to @cloudflare/vitest-pool-workers for Worker runtime
  },
});
