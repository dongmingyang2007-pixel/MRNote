import { render, screen, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { HeaderBar } from "@/components/console/graph/memory-graph/HeaderBar";

afterEach(() => { cleanup(); });

describe("HeaderBar", () => {
  it("renders title + brand suffix", () => {
    render(<HeaderBar />);
    expect(screen.getByText("memoryGraph.title")).toBeTruthy();
    expect(screen.getByText("memoryGraph.header.brand")).toBeTruthy();
  });

  it("renders the graph icon", () => {
    const { container } = render(<HeaderBar />);
    expect(container.querySelector("svg")).toBeTruthy();
  });
});
