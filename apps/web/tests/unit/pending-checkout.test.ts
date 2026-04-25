import { beforeEach, describe, expect, it } from "vitest";

import {
  clearPendingCheckoutPlan,
  isPaidCheckoutPlan,
  isPaidPlanId,
  parsePendingCheckoutPlan,
  persistPendingCheckoutPlan,
  readStoredPendingCheckoutPlan,
} from "@/lib/pending-checkout";

describe("pending checkout plan", () => {
  beforeEach(() => {
    clearPendingCheckoutPlan();
  });

  it("parses pricing plan and cycle from register query params", () => {
    const pendingPlan = parsePendingCheckoutPlan(
      new URLSearchParams("plan=pro&cycle=yearly"),
    );

    expect(pendingPlan).toEqual({ plan: "pro", cycle: "yearly" });
    expect(isPaidCheckoutPlan(pendingPlan)).toBe(true);
  });

  it("defaults missing or invalid cycle to monthly", () => {
    expect(
      parsePendingCheckoutPlan(new URLSearchParams("plan=power")),
    ).toEqual({ plan: "power", cycle: "monthly" });
    expect(
      parsePendingCheckoutPlan(new URLSearchParams("plan=team&cycle=weekly")),
    ).toEqual({ plan: "team", cycle: "monthly" });
  });

  it("ignores unknown plans", () => {
    expect(
      parsePendingCheckoutPlan(new URLSearchParams("plan=enterprise")),
    ).toBeNull();
  });

  it("persists and clears the pending plan in sessionStorage", () => {
    persistPendingCheckoutPlan({ plan: "power", cycle: "monthly" });
    expect(readStoredPendingCheckoutPlan()).toEqual({
      plan: "power",
      cycle: "monthly",
    });

    clearPendingCheckoutPlan();
    expect(readStoredPendingCheckoutPlan()).toBeNull();
  });

  it("distinguishes paid plans from free", () => {
    expect(isPaidPlanId("pro")).toBe(true);
    expect(isPaidPlanId("power")).toBe(true);
    expect(isPaidPlanId("team")).toBe(true);
    expect(isPaidPlanId("free")).toBe(false);
  });
});
