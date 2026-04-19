import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { humanizeRelativeTime } from "@/components/console/graph/memory-graph/humanize";

describe("humanizeRelativeTime", () => {
  const NOW = new Date("2026-04-19T12:00:00Z").getTime();

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });
  afterEach(() => vi.useRealTimers());

  it("returns null for null/undefined/empty", () => {
    expect(humanizeRelativeTime(null)).toBeNull();
    expect(humanizeRelativeTime(undefined)).toBeNull();
    expect(humanizeRelativeTime("")).toBeNull();
  });

  it("returns null for unparseable strings", () => {
    expect(humanizeRelativeTime("not-a-date")).toBeNull();
  });

  it("formats minutes under an hour", () => {
    expect(humanizeRelativeTime(new Date(NOW - 30 * 60_000).toISOString())).toBe("30m");
    expect(humanizeRelativeTime(new Date(NOW - 1 * 60_000).toISOString())).toBe("1m");
    expect(humanizeRelativeTime(new Date(NOW - 0).toISOString())).toBe("0m");
  });

  it("formats hours under a day", () => {
    expect(humanizeRelativeTime(new Date(NOW - 2 * 3600_000).toISOString())).toBe("2h");
    expect(humanizeRelativeTime(new Date(NOW - 23 * 3600_000).toISOString())).toBe("23h");
  });

  it("formats days", () => {
    expect(humanizeRelativeTime(new Date(NOW - 3 * 86400_000).toISOString())).toBe("3d");
    expect(humanizeRelativeTime(new Date(NOW - 30 * 86400_000).toISOString())).toBe("30d");
  });

  it("floors future timestamps to 0m (do not display negative offsets)", () => {
    expect(humanizeRelativeTime(new Date(NOW + 5 * 60_000).toISOString())).toBe("0m");
  });
});
