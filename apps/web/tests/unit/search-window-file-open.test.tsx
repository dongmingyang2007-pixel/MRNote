import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import SearchWindow from "@/components/notebook/contents/SearchWindow";

const openWindow = vi.fn();
const routerPush = vi.fn();

vi.mock("@/components/notebook/WindowManager", () => ({
  useWindowManager: () => ({ openWindow }),
}));

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({
    push: routerPush,
    replace: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

describe("SearchWindow file opening", () => {
  beforeEach(() => {
    openWindow.mockReset();
    routerPush.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("opens study-document file hits via data-item download metadata", async () => {
    global.fetch = vi.fn(async (url: RequestInfo | URL) => {
      const urlStr = String(url);
      if (urlStr.includes("/api/v1/search") || urlStr.includes("/search")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            query: "spec",
            duration_ms: 6,
            results: {
              pages: [],
              blocks: [],
              study_assets: [],
              files: [
                {
                  id: "asset1",
                  asset_id: "asset1",
                  data_item_id: "di1",
                  notebook_id: "nb1",
                  title: "Build Spec.pdf",
                  snippet: "Build Spec.pdf",
                  mime_type: "application/pdf",
                  score: 0.5,
                  source: "lexical",
                },
              ],
              memory: [],
              playbooks: [],
              ai_actions: [],
            },
          }),
        } as Response;
      }
      if (urlStr.includes("/api/v1/data-items/di1")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            id: "di1",
            filename: "Build Spec.pdf",
            media_type: "application/pdf",
            preview_url: null,
            download_url: "https://example.com/build-spec.pdf",
          }),
        } as Response;
      }
      throw new Error(`unexpected fetch ${urlStr}`);
    }) as typeof fetch;

    render(<SearchWindow notebookId="nb1" />);
    fireEvent.change(screen.getByTestId("search-window-input"), {
      target: { value: "spec" },
    });

    const fileHit = await screen.findByText("Build Spec.pdf", {}, { timeout: 3000 });
    fireEvent.click(fileHit);

    await waitFor(() => {
      expect(openWindow).toHaveBeenCalledWith({
        type: "file",
        title: "Build Spec.pdf",
        meta: {
          previewUrl: "",
          downloadUrl: "https://example.com/build-spec.pdf",
          mimeType: "application/pdf",
          filename: "Build Spec.pdf",
        },
      });
    });
  });
});
