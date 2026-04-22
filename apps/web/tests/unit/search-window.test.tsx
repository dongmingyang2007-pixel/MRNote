import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SearchWindow from "@/components/notebook/contents/SearchWindow";
import { WindowManagerProvider } from "@/components/notebook/WindowManager";

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

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
            blocks: [],
            study_assets: [],
            files: [{ id: "f1", attachment_id: "att1", notebook_id: "nb1", title: "Spec.pdf", snippet: "Spec.pdf", score: 0.5, source: "lexical" }],
            memory: [],
            playbooks: [],
            ai_actions: [{ id: "a1", notebook_id: "nb1", page_id: "p1", title: "Summarize page", snippet: "Summary output", score: 0.5, source: "lexical" }],
          },
        }),
      } as Response;
    }
    if (urlStr.includes("/api/v1/attachments/att1/url")) {
      return {
        ok: true, status: 200,
        json: async () => ({ url: "https://example.com/spec.pdf" }),
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
    expect(await screen.findByText("Spec.pdf", {}, { timeout: 3000 })).toBeTruthy();
    expect(await screen.findByText("Summarize page", {}, { timeout: 3000 })).toBeTruthy();
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
