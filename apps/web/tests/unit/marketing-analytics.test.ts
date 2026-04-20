import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { emitLandingEvent } from "@/lib/marketing/analytics";

describe("emitLandingEvent", () => {
  const origDebug = vi.spyOn(console, "debug");

  beforeEach(() => { origDebug.mockClear(); });
  afterEach(() => { vi.unstubAllEnvs(); });

  it("logs in development", () => {
    vi.stubEnv("NODE_ENV", "development");
    emitLandingEvent("landing.role.selected", { role: "researcher", locale: "zh" });
    expect(origDebug).toHaveBeenCalledWith(
      "[mrai.analytics]",
      "landing.role.selected",
      { role: "researcher", locale: "zh" },
    );
  });

  it("is a noop in production", () => {
    vi.stubEnv("NODE_ENV", "production");
    emitLandingEvent("landing.role.selected", { role: "researcher", locale: "zh" });
    expect(origDebug).not.toHaveBeenCalled();
  });
});
