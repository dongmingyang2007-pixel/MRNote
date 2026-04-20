import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...props }: any) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

// StatCounter uses IntersectionObserver which is absent in jsdom.
// Setting prefers-reduced-motion to true makes StatCounter skip the IO path.
const matchMediaMock = vi.fn().mockImplementation((query: string) => ({
  matches: query.includes("prefers-reduced-motion"),
  media: query,
  onchange: null,
  addListener: vi.fn(),
  removeListener: vi.fn(),
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
  dispatchEvent: vi.fn(),
}));
Object.defineProperty(window, "matchMedia", {
  value: matchMediaMock,
  writable: true,
  configurable: true,
});

import ExclusiveSection from "@/components/marketing/ExclusiveSection";

function clearAllCookies() {
  document.cookie
    .split(";")
    .map((c) => c.trim().split("=")[0])
    .filter(Boolean)
    .forEach((name) => {
      document.cookie = `${name}=; Max-Age=0; Path=/`;
    });
}

describe("ExclusiveSection", () => {
  beforeEach(() => clearAllCookies());
  afterEach(() => {
    clearAllCookies();
    cleanup();
  });

  it("renders the empty state with placeholder cards when no role selected", () => {
    render(<ExclusiveSection initialRole={null} locale="zh" />);
    expect(screen.getByText("exclusiveSection.emptyTitle")).toBeTruthy();
    expect(screen.queryByText("立即激活 →")).toBeNull();
    const placeholders = screen.getAllByText("exclusiveSection.placeholderCard");
    expect(placeholders.length).toBeGreaterThanOrEqual(3);
  });

  it("renders role content when initialRole is provided", () => {
    render(<ExclusiveSection initialRole="researcher" locale="zh" />);
    expect(screen.getByText("文献综述自动整理")).toBeTruthy();
    expect(screen.getByText("研究生 5 件套")).toBeTruthy();
    expect(screen.getByText(".edu 邮箱 · Pro 免费 6 月")).toBeTruthy();
  });

  it("selecting a chip swaps the populated content", () => {
    render(<ExclusiveSection initialRole={null} locale="zh" />);
    act(() => {
      fireEvent.click(screen.getByRole("radio", { name: "律师" }));
    });
    expect(screen.getByText("合同摘要 10 秒出")).toBeTruthy();
  });

  it("switch link clears the role and returns to empty state", () => {
    render(<ExclusiveSection initialRole="lawyer" locale="zh" />);
    const switchBtn = screen.getByRole("button", { name: "exclusiveSection.switch" });
    act(() => { fireEvent.click(switchBtn); });
    expect(screen.queryByText("合同摘要 10 秒出")).toBeNull();
    expect(screen.getByText("exclusiveSection.emptyTitle")).toBeTruthy();
  });
});
