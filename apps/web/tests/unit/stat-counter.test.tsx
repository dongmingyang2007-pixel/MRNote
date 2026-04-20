import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import StatCounter from "@/components/marketing/role-selector/StatCounter";

describe("StatCounter", () => {
  const originalMatchMedia = window.matchMedia;

  afterEach(() => {
    window.matchMedia = originalMatchMedia;
    vi.useRealTimers();
  });

  function setReducedMotion(matches: boolean) {
    window.matchMedia = vi.fn().mockImplementation((query) => ({
      matches: query.includes("prefers-reduced-motion") && matches,
      media: query, onchange: null,
      addListener: vi.fn(), removeListener: vi.fn(),
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
  }

  it("renders the final value immediately when reduced-motion is requested", () => {
    setReducedMotion(true);
    render(<StatCounter target={5243} />);
    expect(screen.getByText("5,243")).toBeTruthy();
  });

  it("announces the final value via aria-live", () => {
    setReducedMotion(true);
    const { container } = render(<StatCounter target={100} />);
    const el = container.querySelector('[aria-live="polite"]');
    expect(el).not.toBeNull();
    expect(el!.textContent).toContain("100");
  });

  it("formats numbers with thousand separators", () => {
    setReducedMotion(true);
    render(<StatCounter target={12345} />);
    expect(screen.getByText("12,345")).toBeTruthy();
  });
});
