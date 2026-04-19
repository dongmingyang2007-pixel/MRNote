import { render, screen, waitFor, cleanup } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import MemoryGraphWindow from "@/components/notebook/contents/MemoryGraphWindow";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));
vi.mock("@/lib/env", () => ({ getApiHttpBaseUrl: () => "http://localhost" }));
vi.mock("@/hooks/useGraphData", () => ({
  useGraphData: vi.fn(),
}));

import { apiGet } from "@/lib/api";
import { useGraphData } from "@/hooks/useGraphData";

beforeEach(() => {
  vi.mocked(apiGet).mockReset();
  vi.mocked(useGraphData).mockReset();
});
afterEach(() => { cleanup(); });

describe("MemoryGraphWindow", () => {
  it("renders loading state initially", () => {
    vi.mocked(apiGet).mockImplementation(() => new Promise(() => {})); // never resolves
    vi.mocked(useGraphData).mockReturnValue({
      data: { nodes: [], edges: [] },
      loading: true,
      refetch: vi.fn(),
      createMemory: vi.fn(),
      updateMemory: vi.fn(),
      deleteMemory: vi.fn(),
      promoteMemory: vi.fn(),
      createEdge: vi.fn(),
      deleteEdge: vi.fn(),
      attachFileToMemory: vi.fn(),
      detachFileFromMemory: vi.fn(),
    });
    render(<MemoryGraphWindow notebookId="nb1" />);
    expect(screen.getByText("memoryGraph.loading")).toBeTruthy();
  });

  it("resolves projectId from notebook endpoint and then loads graph", async () => {
    vi.mocked(apiGet).mockImplementation((url: string) => {
      if (url.startsWith("/api/v1/notebooks/")) {
        return Promise.resolve({ project_id: "p1" });
      }
      return Promise.reject(new Error(`unexpected: ${url}`));
    });
    vi.mocked(useGraphData).mockReturnValue({
      data: { nodes: [], edges: [] },
      loading: false,
      refetch: vi.fn(),
      createMemory: vi.fn(),
      updateMemory: vi.fn(),
      deleteMemory: vi.fn(),
      promoteMemory: vi.fn(),
      createEdge: vi.fn(),
      deleteEdge: vi.fn(),
      attachFileToMemory: vi.fn(),
      detachFileFromMemory: vi.fn(),
    });
    render(<MemoryGraphWindow notebookId="nb1" />);
    await waitFor(() => {
      expect(screen.getByText("memoryGraph.empty.title")).toBeTruthy();
    });
  });
});
