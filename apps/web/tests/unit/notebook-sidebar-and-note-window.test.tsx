import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiGet = vi.fn();
const renameWindowByMeta = vi.fn();

vi.mock("@/i18n/navigation", () => ({
  Link: ({
    children,
    href,
  }: {
    children: React.ReactNode;
    href: string;
  }) => <a href={href}>{children}</a>,
  usePathname: () => "/en/app/notebooks/nb-1",
}));

vi.mock("@/lib/api", () => ({
  apiGet: (...args: unknown[]) => apiGet(...args),
  apiPost: vi.fn(),
}));

vi.mock("@/components/notebook/WindowManager", () => ({
  useWindowManager: () => ({
    openWindow: vi.fn(),
    renameWindowByMeta,
  }),
  useWindows: () => [],
}));

vi.mock("@/hooks/useDigestUnreadCount", () => ({
  useDigestUnreadCount: () => 0,
}));

vi.mock("@/hooks/useBillingMe", () => ({
  useBillingMe: () => null,
}));

vi.mock("@/components/notebook/MinimizedTray", () => ({
  default: () => null,
}));

vi.mock("@/components/console/editor/NoteEditor", () => ({
  default: ({
    onTitleChange,
  }: {
    onTitleChange?: (title: string) => void;
  }) => (
    <button
      type="button"
      data-testid="rename-note"
      onClick={() => onTitleChange?.("Renamed page")}
    >
      rename
    </button>
  ),
}));

vi.mock(
  "@/components/notebook/contents/search/RelatedPagesCard",
  () => ({
    default: () => null,
  }),
);

import NotebookSidebar from "@/components/console/NotebookSidebar";
import NoteWindow from "@/components/notebook/contents/NoteWindow";
import { NOTEBOOK_PAGES_CHANGED_EVENT } from "@/lib/notebook-events";

describe("NotebookSidebar and NoteWindow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiGet.mockResolvedValue({
      items: [{ id: "page-1", title: "First page", page_type: "document" }],
    });
  });

  it("boots with a bare canvas and no pages panel open", () => {
    render(<NotebookSidebar notebookId="nb-1" />);
    expect(screen.queryByTestId("sidebar-panel-close")).toBeNull();
  });

  it("dispatches a page-list refresh after renaming a note title", () => {
    vi.useFakeTimers();
    const refreshListener = vi.fn();
    window.addEventListener(NOTEBOOK_PAGES_CHANGED_EVENT, refreshListener);

    render(<NoteWindow pageId="page-1" />);
    fireEvent.click(screen.getByTestId("rename-note"));

    expect(renameWindowByMeta).toHaveBeenCalledWith(
      "pageId",
      "page-1",
      "Renamed page",
    );

    vi.advanceTimersByTime(250);
    expect(refreshListener).toHaveBeenCalledTimes(1);

    window.removeEventListener(NOTEBOOK_PAGES_CHANGED_EVENT, refreshListener);
    vi.useRealTimers();
  });
});
