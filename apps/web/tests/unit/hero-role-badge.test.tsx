import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Mock server-only next-intl helper used by HeroSection.
// Load actual i18n messages for proper testing.
import zhMessages from "@/messages/zh/marketing.json";
import enMessages from "@/messages/en/marketing.json";

vi.mock("next-intl/server", () => ({
  getTranslations: async (_ns?: string) => (key: string, values?: Record<string, string>) => {
    // Return the actual message for testing (simplified mock for unit tests)
    const messages: Record<string, Record<string, string>> = {
      zh: zhMessages as Record<string, string>,
      en: enMessages as Record<string, string>,
    };
    // For simplicity, default to Chinese in this test mock
    let message = messages.zh[key] || key;
    if (values) {
      Object.keys(values).forEach((name) => {
        message = message.replaceAll(`{${name}}`, String(values[name]));
      });
    }
    return message;
  },
}));

// Stub heavy client children so the server component renders plainly in jsdom.
vi.mock("@/components/marketing/HeroAnimatedClient", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/marketing/HeroCanvasStage", () => ({
  default: () => null,
}));

// next-intl Link used by HeroSection for the CTA row
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode; [k: string]: unknown }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

import HeroSection from "@/components/marketing/HeroSection";

async function renderServer(jsx: Promise<React.ReactElement>) {
  const el = await jsx;
  return render(el);
}

describe("HeroSection role badge", () => {
  it("does not render the badge when role is null", async () => {
    await renderServer(HeroSection({ role: null, locale: "zh" }) as unknown as Promise<React.ReactElement>);
    expect(screen.queryByTestId("hero-role-badge")).toBeNull();
  });

  it("renders the badge with the role label when role is set", async () => {
    await renderServer(HeroSection({ role: "researcher", locale: "zh" }) as unknown as Promise<React.ReactElement>);
    const badge = screen.getByTestId("hero-role-badge");
    expect(badge.textContent).toContain("研究生");
  });
});
