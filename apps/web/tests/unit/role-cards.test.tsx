import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...props }: any) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

import RoleCard from "@/components/marketing/role-selector/RoleCard";
import ExclusiveOfferCard from "@/components/marketing/role-selector/ExclusiveOfferCard";

describe("RoleCard", () => {
  it("renders label, title, description, and cta", () => {
    render(
      <RoleCard
        label="场景 DEMO"
        title="文献综述自动整理"
        description="看 MRNote 如何把 50 篇论文整理成可引用的综述。"
        cta="免费导入 →"
      />,
    );
    expect(screen.getByText("场景 DEMO")).toBeTruthy();
    expect(screen.getByText("文献综述自动整理")).toBeTruthy();
    expect(screen.getByText("免费导入 →")).toBeTruthy();
  });
});

describe("ExclusiveOfferCard", () => {
  it("renders title, description, CTA link, and the 独家 badge", () => {
    render(
      <ExclusiveOfferCard
        label="专属优惠"
        title=".edu 邮箱 · Pro 免费 6 月"
        description="验证学生身份即可激活，无需信用卡。"
        cta="立即激活 →"
        href="/register?offer=edu-6m"
        badge="独家"
      />,
    );
    const link = screen.getByRole("link", { name: /立即激活/ });
    expect(link.getAttribute("href")).toBe("/register?offer=edu-6m");
    expect(screen.getByText("独家")).toBeTruthy();
  });
});
