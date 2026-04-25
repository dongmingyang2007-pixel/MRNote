import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
const replace = vi.fn();
const openWindow = vi.fn();
const apiGet = vi.fn();

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({
    push,
    replace,
    prefetch: vi.fn(),
  }),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ notebookId: "nb-1" }),
  useSearchParams: () => new URLSearchParams("openPage=page-1"),
}));

vi.mock("@/lib/api", () => ({
  apiGet: (...args: unknown[]) => apiGet(...args),
  apiPost: vi.fn(),
  apiDelete: vi.fn(),
}));

vi.mock("@/lib/auth-state", () => ({
  subscribeAuthState: () => () => {},
  getAuthStateClientSnapshot: () => true,
  getAuthStateHydrationSnapshot: () => true,
}));

vi.mock("@/components/notebook/WindowManager", () => ({
  useWindowManager: () => ({ openWindow }),
  useWindows: () => [],
}));

vi.mock("@/components/notebook/WindowCanvas", () => ({
  default: () => <div data-testid="window-canvas" />,
}));

import NotebookDetailPage from "@/app/[locale]/workspace/notebooks/[notebookId]/page";
import NotebooksPage from "@/app/[locale]/workspace/notebooks/page";

describe("notebook navigation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("routes notebook home interactions through the locale-aware router", async () => {
    apiGet.mockResolvedValue({
      notebooks: [
        {
          id: "nb-1",
          title: "Notebook One",
          description: "",
          notebook_type: "personal",
          updated_at: "2026-04-21T18:00:00Z",
          page_count: 1,
          study_asset_count: 0,
          ai_action_count: 0,
        },
      ],
      recent_pages: [],
      continue_writing: [],
      recent_study_assets: [],
      ai_today: { actions_today: 0, top_action_types: [], recent_actions: [] },
      work_themes: [],
      long_term_focus: [],
      recommended_pages: [],
    });

    render(<NotebooksPage />);

    const card = await screen.findByTestId("notebook-card");
    fireEvent.click(card);

    expect(push).toHaveBeenCalledWith("/app/notebooks/nb-1");
  });

  it("consumes ?openPage= via the locale-aware router replace path", async () => {
    render(<NotebookDetailPage />);

    await waitFor(() => {
      expect(openWindow).toHaveBeenCalledWith({
        type: "note",
        title: "pages.untitled",
        meta: { notebookId: "nb-1", pageId: "page-1" },
      });
    });
    expect(replace).toHaveBeenCalledWith("/app/notebooks/nb-1");
  });
});
