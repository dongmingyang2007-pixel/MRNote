import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SearchWindow from "@/components/notebook/contents/SearchWindow";
import { WindowManagerProvider } from "@/components/notebook/WindowManager";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function mockFetch() {
  global.fetch = vi.fn(async (url: RequestInfo | URL) => {
    const urlStr = String(url);
    if (urlStr.includes("/api/v1/auth/csrf")) {
      return {
        ok: true, status: 200,
        json: async () => ({ csrf_token: "t" }),
      } as Response;
    }
    if (urlStr.includes("/api/v1/search") || urlStr.includes("/search")) {
      return {
        ok: true, status: 200,
        json: async () => ({
          query: "login", duration_ms: 5,
          results: {
            pages: [{ id: "p1", notebook_id: "nb1", title: "Login flow",
                      snippet: "x", score: 0.8, source: "rrf" }],
            blocks: [], study_assets: [], memory: [], playbooks: [],
          },
        }),
      } as Response;
    }
    throw new Error("unexpected fetch " + urlStr);
  }) as typeof fetch;
}

describe("SearchWindow", () => {
  it("renders input and populates pages group after typing", async () => {
    mockFetch();
    render(
      <WindowManagerProvider notebookId="nb1">
        <SearchWindow notebookId="nb1" />
      </WindowManagerProvider>,
    );
    const input = screen.getByTestId("search-window-input");
    fireEvent.change(input, { target: { value: "login" } });
    const item = await screen.findByText("Login flow", {}, { timeout: 3000 });
    expect(item).toBeTruthy();
  });

  it("renders empty state when no query", () => {
    mockFetch();
    render(
      <WindowManagerProvider notebookId="nb1">
        <SearchWindow notebookId="nb1" />
      </WindowManagerProvider>,
    );
    const input = screen.getByTestId("search-window-input");
    expect((input as HTMLInputElement).value).toBe("");
  });
});
