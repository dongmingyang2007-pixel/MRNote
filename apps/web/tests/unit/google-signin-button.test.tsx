import { render, screen, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("next=/app/notebooks/123"),
}));

import GoogleSignInButton from "@/components/auth/GoogleSignInButton";

describe("GoogleSignInButton", () => {
  afterEach(() => cleanup());

  it("renders an <a> pointing at /api/v1/auth/google/authorize with signin mode", () => {
    render(<GoogleSignInButton />);
    const link = screen.getByTestId("google-signin-link");
    expect(link.tagName).toBe("A");
    const href = link.getAttribute("href") || "";
    expect(href.startsWith("/api/v1/auth/google/authorize")).toBe(true);
    expect(href).toContain("mode=signin");
    // URL-encoded /app/notebooks/123
    expect(href).toContain("next=%2Fapp%2Fnotebooks%2F123");
  });

  it("respects mode=connect prop", () => {
    render(<GoogleSignInButton mode="connect" />);
    const link = screen.getByTestId("google-signin-link");
    expect(link.getAttribute("href")).toContain("mode=connect");
  });

  it("renders the localised button label", () => {
    render(<GoogleSignInButton />);
    // Mock returns the key string itself, which is enough to prove
    // the translation channel was used.
    expect(screen.getByText("oauth.google.button")).toBeDefined();
  });
});
