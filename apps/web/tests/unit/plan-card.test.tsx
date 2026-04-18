import { render, screen, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PlanCard, { type PlanDescriptor } from "@/components/billing/PlanCard";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const PLAN_FREE: PlanDescriptor = {
  id: "free", name: "Free", monthlyPrice: null, yearlyPrice: null,
  features: ["1 notebook"],
};
const PLAN_PRO: PlanDescriptor = {
  id: "pro", name: "Pro", monthlyPrice: 10, yearlyPrice: 102,
  features: ["Unlimited notebooks"],
};

describe("PlanCard", () => {
  it("renders Free with no upgrade button", () => {
    render(<PlanCard plan={PLAN_FREE} cycle="monthly" isCurrent={false} />);
    expect(screen.queryByTestId("plan-card-free-upgrade")).toBeNull();
  });

  it("renders Pro monthly with upgrade button", () => {
    render(<PlanCard plan={PLAN_PRO} cycle="monthly" isCurrent={false} />);
    const btn = screen.getByTestId("plan-card-pro-upgrade");
    expect(btn).toBeTruthy();
    expect(screen.getByText(/\$10/)).toBeTruthy();
  });

  it("highlights current plan and hides upgrade", () => {
    render(<PlanCard plan={PLAN_PRO} cycle="monthly" isCurrent={true} />);
    expect(screen.queryByTestId("plan-card-pro-upgrade")).toBeNull();
    // The mocked next-intl translator echoes the i18n key directly.
    expect(screen.getByText("plan.currentLabel")).toBeTruthy();
  });
});
