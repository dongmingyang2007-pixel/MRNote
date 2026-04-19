import { render, screen, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// jsdom has no WebGL — mock the scene hook to return a stub handle.
vi.mock("@/components/console/graph/memory-graph/Memory3D/useThreeScene", () => ({
  useThreeScene: () => ({
    focusOn: vi.fn(),
    rearrange: vi.fn(),
    zoomIn: vi.fn(),
    zoomOut: vi.fn(),
    fit: vi.fn(),
    toggleAutoRotate: vi.fn(),
    getProjectedScreenPos: vi.fn(() => null),
  }),
}));

import { Memory3D } from "@/components/console/graph/memory-graph/Memory3D/Memory3D";
import type { GraphNode } from "@/components/console/graph/memory-graph/types";

function n(over: Partial<GraphNode>): GraphNode {
  return {
    id: "a", role: "fact", label: "Alpha", conf: 0.9, reuse: 0,
    lastUsed: null, pinned: false, source: null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    raw: {} as any, ...over,
  };
}

afterEach(() => { cleanup(); });

describe("Memory3D", () => {
  it("renders mount container + camera controls HUD", () => {
    render(<Memory3D nodes={[n({})]} edges={[]} selectedId={null} hoverId={null} onHover={() => {}} onSelect={() => {}} />);
    expect(screen.getByTestId("mg3d-mount")).toBeTruthy();
    expect(screen.getByTestId("mg3d-fit")).toBeTruthy();
  });
});
