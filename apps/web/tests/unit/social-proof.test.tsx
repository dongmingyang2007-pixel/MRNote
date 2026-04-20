import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import TestimonialStrip from "@/components/marketing/role-selector/TestimonialStrip";
import InstitutionLogoRow from "@/components/marketing/role-selector/InstitutionLogoRow";

describe("TestimonialStrip", () => {
  it("renders quote, attribution, and decorative avatar initial", () => {
    render(
      <TestimonialStrip
        quote="写论文最痛的一步是把之前读过的文献重新串起来。"
        name="李同学"
        title="清华大学 · 计算机博二"
        avatarInitial="李"
      />,
    );
    expect(screen.getByText(/写论文最痛的一步/)).toBeTruthy();
    expect(screen.getByText("李同学 · 清华大学 · 计算机博二")).toBeTruthy();
    const avatar = screen.getByText("李", { selector: "[aria-hidden='true']" });
    expect(avatar).toBeTruthy();
  });
});

describe("InstitutionLogoRow", () => {
  it("renders all 5 institution names with a heading", () => {
    render(
      <InstitutionLogoRow
        heading="使用 MRNote 的研究机构"
        names={["清华大学", "北京大学", "中科院", "复旦大学", "浙江大学"]}
      />,
    );
    expect(screen.getByText("使用 MRNote 的研究机构")).toBeTruthy();
    ["清华大学", "北京大学", "中科院", "复旦大学", "浙江大学"].forEach((n) => {
      expect(screen.getByText(n)).toBeTruthy();
    });
  });
});
