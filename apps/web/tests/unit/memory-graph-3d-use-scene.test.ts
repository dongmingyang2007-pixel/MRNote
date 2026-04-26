import { renderHook, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useThreeScene } from "@/components/console/graph/memory-graph/Memory3D/useThreeScene";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("useThreeScene", () => {
  it("returns a scene handle even with no mount", () => {
    const { result } = renderHook(() => useThreeScene({
      mountRef: { current: null } as unknown as React.RefObject<HTMLDivElement>,
      nodes: [], edges: [],
      onHover: () => {}, onSelect: () => {},
    }));
    expect(result.current).toBeDefined();
  });

  it("exposes handle methods", () => {
    const { result } = renderHook(() => useThreeScene({
      mountRef: { current: null } as unknown as React.RefObject<HTMLDivElement>,
      nodes: [], edges: [],
      onHover: () => {}, onSelect: () => {},
    }));
    const h = result.current;
    expect(typeof h.focusOn).toBe("function");
    expect(typeof h.rearrange).toBe("function");
    expect(typeof h.zoomIn).toBe("function");
    expect(typeof h.zoomOut).toBe("function");
    expect(typeof h.fit).toBe("function");
    expect(typeof h.toggleAutoRotate).toBe("function");
    expect(typeof h.getProjectedScreenPos).toBe("function");
  });
});
