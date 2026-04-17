import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import DigestList from "@/components/notebook/contents/digest/DigestList";

afterEach(() => {
  vi.restoreAllMocks();
});

const SAMPLE = [
  {
    id: "d1", kind: "daily_digest", title: "Daily",
    period_start: "2026-04-17T00:00:00Z", period_end: "2026-04-18T00:00:00Z",
    status: "unread",
    created_at: new Date(Date.now() - 1000).toISOString(),
  },
  {
    id: "d2", kind: "weekly_reflection", title: "Week",
    period_start: "2026-04-10T00:00:00Z", period_end: "2026-04-17T00:00:00Z",
    status: "read",
    created_at: new Date(Date.now() - 86400_000 * 2).toISOString(),
  },
];

// apiGet (GET) calls ensureCsrfToken first (/api/v1/auth/csrf), then the real
// endpoint. Both fetch calls must return ok responses for the component to
// render. getApiHttpBaseUrl() returns "" in jsdom (no NEXT_PUBLIC_API_BASE_URL
// env), so the URLs are plain paths like "/api/v1/auth/csrf".
function mockFetch(items: typeof SAMPLE) {
  global.fetch = vi.fn(async (url: RequestInfo | URL) => {
    const urlStr = String(url);
    if (urlStr.includes("/api/v1/auth/csrf")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ csrf_token: "test-csrf-token" }),
      } as Response;
    }
    if (urlStr.includes("/api/v1/digests")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          items,
          next_cursor: null,
          unread_count: items.filter((i) => i.status === "unread").length,
        }),
      } as Response;
    }
    throw new Error("unexpected fetch " + url);
  }) as typeof fetch;
}

describe("DigestList", () => {
  it("renders each item and shows the unread dot for unread rows", async () => {
    mockFetch(SAMPLE);
    const onPick = vi.fn();
    render(<DigestList onPick={onPick} />);
    await screen.findByText("Daily");
    // "Week" is in the DOM if getByText doesn't throw
    expect(screen.getByText("Week")).toBeTruthy();
    const unreadDots = screen.getAllByTestId("digest-unread-dot");
    expect(unreadDots).toHaveLength(1);
  });

  it("renders empty state when api returns no items", async () => {
    mockFetch([]);
    const onPick = vi.fn();
    render(<DigestList onPick={onPick} />);
    await screen.findByText(/Nothing here/i);
  });
});
