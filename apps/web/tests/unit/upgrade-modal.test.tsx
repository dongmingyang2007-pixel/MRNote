import { render, screen, act, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import UpgradeModal from "@/components/billing/UpgradeModal";

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("UpgradeModal", () => {
  it("renders nothing initially", () => {
    const { container } = render(<UpgradeModal />);
    expect(container.querySelector("[data-testid='upgrade-modal']")).toBeNull();
  });

  it("renders when mrai:plan-required event fires", () => {
    render(<UpgradeModal />);
    act(() => {
      window.dispatchEvent(new CustomEvent("mrai:plan-required", {
        detail: { code: "plan_limit_reached", message: "Notebooks limit reached",
                  details: { key: "notebooks.max", current: 1, limit: 1 } },
      }));
    });
    expect(screen.getByTestId("upgrade-modal")).toBeTruthy();
    expect(screen.getByText("upgrade.required.limitBody")).toBeTruthy();
    expect(screen.queryByText(/notebooks\.max/)).toBeNull();
  });
});
