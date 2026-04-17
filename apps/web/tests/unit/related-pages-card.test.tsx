import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import RelatedPagesCard from "@/components/notebook/contents/search/RelatedPagesCard";
import { WindowManagerProvider } from "@/components/notebook/WindowManager";

afterEach(() => { vi.restoreAllMocks(); });

function mockFetch(withResults: boolean) {
  global.fetch = vi.fn(async (url: RequestInfo | URL) => {
    const u = String(url);
    if (u.includes("/api/v1/auth/csrf")) {
      return { ok: true, status: 200,
               json: async () => ({ csrf_token: "t" }) } as Response;
    }
    if (u.includes("/related")) {
      return {
        ok: true, status: 200,
        json: async () => withResults
          ? { pages: [{ id: "pp", notebook_id: "nb",
                        title: "Linked", score: 0.7, reason: "semantic" }],
              memory: [] }
          : { pages: [], memory: [] },
      } as Response;
    }
    throw new Error("unexpected " + u);
  }) as typeof fetch;
}

describe("RelatedPagesCard", () => {
  it("does not render when results are empty", async () => {
    mockFetch(false);
    const { container } = render(
      <WindowManagerProvider notebookId="nb">
        <RelatedPagesCard pageId="p1" />
      </WindowManagerProvider>,
    );
    await new Promise((r) => setTimeout(r, 50));
    expect(container.querySelector("[data-testid='related-pages-card']"))
      .toBeNull();
  });

  it("renders when there are related items", async () => {
    mockFetch(true);
    render(
      <WindowManagerProvider notebookId="nb">
        <RelatedPagesCard pageId="p1" />
      </WindowManagerProvider>,
    );
    const card = await screen.findByTestId(
      "related-pages-card", {}, { timeout: 2000 },
    );
    expect(card).toBeTruthy();
  });
});
