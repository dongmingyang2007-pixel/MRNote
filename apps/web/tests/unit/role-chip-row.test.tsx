import { fireEvent, render, screen, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import RoleChipRow from "@/components/marketing/role-selector/RoleChipRow";

describe("RoleChipRow", () => {
  afterEach(() => cleanup());
  it("renders all 6 chips with role labels", () => {
    render(<RoleChipRow activeRole={null} onSelect={() => {}} locale="zh" />);
    expect(screen.getByRole("radio", { name: "研究生" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "律师" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "医生" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "老师" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "创业者" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "设计师" })).toBeTruthy();
  });

  it("marks the active chip with aria-checked=true", () => {
    render(<RoleChipRow activeRole="lawyer" onSelect={() => {}} locale="zh" />);
    expect(screen.getByRole("radio", { name: "律师" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("radio", { name: "研究生" }).getAttribute("aria-checked")).toBe("false");
  });

  it("fires onSelect when a chip is clicked", () => {
    const onSelect = vi.fn();
    render(<RoleChipRow activeRole={null} onSelect={onSelect} locale="zh" />);
    fireEvent.click(screen.getByRole("radio", { name: "医生" }));
    expect(onSelect).toHaveBeenCalledWith("doctor");
  });

  it("arrow-right moves focus to next chip and fires onSelect", () => {
    const onSelect = vi.fn();
    render(<RoleChipRow activeRole="researcher" onSelect={onSelect} locale="zh" />);
    const first = screen.getByRole("radio", { name: "研究生" });
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowRight" });
    expect(onSelect).toHaveBeenCalledWith("lawyer");
  });

  it("arrow-left from first wraps to last", () => {
    const onSelect = vi.fn();
    render(<RoleChipRow activeRole="researcher" onSelect={onSelect} locale="zh" />);
    const first = screen.getByRole("radio", { name: "研究生" });
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowLeft" });
    expect(onSelect).toHaveBeenCalledWith("designer");
  });

  it("renders English labels when locale=en", () => {
    render(<RoleChipRow activeRole={null} onSelect={() => {}} locale="en" />);
    expect(screen.getByRole("radio", { name: "Researcher" })).toBeTruthy();
  });
});
