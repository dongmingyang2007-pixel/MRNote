import { render, screen, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// KaTeX pulls in CSS with url() imports that jsdom doesn't parse.
vi.mock("katex/dist/katex.min.css", () => ({}));

import MarkdownContent from "@/components/console/chat/MarkdownContent";

describe("MarkdownContent", () => {
  afterEach(() => cleanup());

  it("renders markdown headings and bold text", () => {
    const { container } = render(
      <MarkdownContent text={"#### 4. **选择定则与跃迁矩阵元**"} />,
    );
    const h4 = container.querySelector("h4");
    expect(h4).not.toBeNull();
    expect(h4?.textContent).toContain("选择定则");
    expect(container.querySelector("strong")).not.toBeNull();
  });

  it("renders inline LaTeX via remark-math + rehype-katex", () => {
    const { container } = render(
      <MarkdownContent text={"电偶极跃迁矩阵元 \\( \\langle f | \\hat{d} | i \\rangle \\)"} />,
    );
    // KaTeX outputs elements with class name "katex" when math is processed.
    expect(container.querySelector(".katex")).not.toBeNull();
  });

  it("renders display LaTeX in \\[...\\] delimiters", () => {
    const { container } = render(
      <MarkdownContent text={"Energy: \\[ E = m c^2 \\]"} />,
    );
    expect(container.querySelector(".katex-display")).not.toBeNull();
  });

  it("renders streaming mode as plaintext (no markdown parsing)", () => {
    const raw = "**bold** should stay raw while streaming";
    render(<MarkdownContent text={raw} streaming />);
    expect(screen.getByText(raw)).toBeDefined();
  });

  it("opens links in a new tab", () => {
    const { container } = render(
      <MarkdownContent text={"see [docs](https://example.com)"} />,
    );
    const a = container.querySelector("a");
    expect(a?.getAttribute("target")).toBe("_blank");
    expect(a?.getAttribute("rel")).toContain("noopener");
  });
});
