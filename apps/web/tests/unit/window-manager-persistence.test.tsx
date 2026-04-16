import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import {
  STORAGE_KEY_PREFIX,
  CURRENT_SCHEMA_VERSION,
} from "@/components/notebook/window-persistence";
import {
  WindowManagerProvider,
  useWindowManager,
} from "@/components/notebook/WindowManager";

// Small test harness that reaches into the provider.
function Harness({ onReady }: { onReady: (api: ReturnType<typeof useWindowManager>) => void }) {
  const api = useWindowManager();
  onReady(api);
  return null;
}

beforeEach(() => {
  window.localStorage.clear();
});

describe("WindowManagerProvider persistence", () => {
  it("hydrates from localStorage on mount", () => {
    window.localStorage.setItem(
      STORAGE_KEY_PREFIX + "nb1",
      JSON.stringify({
        v: CURRENT_SCHEMA_VERSION,
        windows: [
          {
            id: "w1",
            type: "note",
            title: "hydrated",
            x: 5,
            y: 6,
            width: 780,
            height: 600,
            zIndex: 1,
            minimized: false,
            maximized: false,
            meta: { pageId: "p1", notebookId: "nb1" },
          },
        ],
      }),
    );

    let api: ReturnType<typeof useWindowManager> | undefined;
    render(
      <WindowManagerProvider notebookId="nb1">
        <Harness onReady={(a) => { api = a; }} />
      </WindowManagerProvider>,
    );
    expect(api?.windows).toHaveLength(1);
    expect(api?.windows[0].title).toBe("hydrated");
  });

  it("persists changes back to localStorage", async () => {
    let api: ReturnType<typeof useWindowManager> | undefined;
    render(
      <WindowManagerProvider notebookId="nb2">
        <Harness onReady={(a) => { api = a; }} />
      </WindowManagerProvider>,
    );
    act(() => {
      api?.openWindow({
        type: "note",
        title: "t",
        meta: { pageId: "p1", notebookId: "nb2" },
      });
    });
    // Wait for debounced persist (500ms)
    await new Promise((r) => setTimeout(r, 600));
    const raw = window.localStorage.getItem(STORAGE_KEY_PREFIX + "nb2");
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw!);
    expect(parsed.v).toBe(CURRENT_SCHEMA_VERSION);
    expect(parsed.windows).toHaveLength(1);
    expect(parsed.windows[0].title).toBe("t");
  });
});
