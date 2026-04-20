import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import zhMessages from "@/messages/zh/marketing.json";
import enMessages from "@/messages/en/marketing.json";

const allMessages: Record<string, Record<string, string>> = {
  zh: zhMessages as Record<string, string>,
  en: enMessages as Record<string, string>,
};

// HeroRoleBadge always uses useTranslations("marketing") without a locale arg.
// The locale drives which label comes from ROLE_CONTENT; the message template
// also needs the right locale so interpolation produces the expected string.
// We expose a module-level mutable so tests can set it before rendering.
let _mockLocale: "zh" | "en" = "zh";

vi.mock("next-intl", () => ({
  useTranslations: (_ns?: string) => (key: string, values?: Record<string, string>) => {
    let message = (allMessages[_mockLocale]?.[key]) ?? key;
    if (values) {
      Object.keys(values).forEach((name) => {
        message = message.replaceAll(`{${name}}`, String(values[name]));
      });
    }
    return message;
  },
}));

import HeroRoleBadge from "@/components/marketing/HeroRoleBadge";
import { RoleProvider } from "@/lib/marketing/RoleContext";

describe("HeroRoleBadge", () => {
  afterEach(() => { cleanup(); _mockLocale = "zh"; });

  it("renders nothing when no role is selected", () => {
    render(
      <RoleProvider initialRole={null}>
        <HeroRoleBadge locale="zh" />
      </RoleProvider>,
    );
    expect(screen.queryByTestId("hero-role-badge")).toBeNull();
  });

  it("renders the badge with the localized role label when a role is provided", () => {
    _mockLocale = "zh";
    render(
      <RoleProvider initialRole="researcher">
        <HeroRoleBadge locale="zh" />
      </RoleProvider>,
    );
    const badge = screen.getByTestId("hero-role-badge");
    expect(badge.textContent).toContain("研究生");
  });

  it("renders English label when locale=en", () => {
    _mockLocale = "en";
    render(
      <RoleProvider initialRole="researcher">
        <HeroRoleBadge locale="en" />
      </RoleProvider>,
    );
    const badge = screen.getByTestId("hero-role-badge");
    expect(badge.textContent).toContain("Researcher");
  });
});
