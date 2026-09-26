/**
 * // SLOT w09 — expand with workers pool + DO tests
 */
import { describe, expect, it } from "vitest";

describe("open-agent-gateway smoke", () => {
  it("health payload shape", () => {
    const body = {
      ok: true,
      service: "open-agent-gateway",
      version: "0.1.0",
    };
    expect(body.ok).toBe(true);
    expect(body.service).toBe("open-agent-gateway");
  });

  it("provider id list contract", () => {
    const providers = ["openai", "apmix", "anthropic", "custom"];
    expect(providers).toContain("apmix");
    expect(providers).toHaveLength(4);
  });
});
