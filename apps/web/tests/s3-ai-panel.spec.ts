import { test, expect } from "@playwright/test";

async function bootstrapNotebookWithPage(page: import("@playwright/test").Page) {
  await page.goto("/workspace/notebooks");
  await page.getByRole("button", { name: /create/i }).first().click();
  await page.waitForURL(/\/workspace\/notebooks\/[^/]+$/);
  await page.getByRole("button", { name: /create/i }).first().click();
  // Ensure the note window is rendered.
  await expect(page.locator(".wm-window").first()).toBeVisible();
}

test.describe("S3 AI Panel", () => {
  test("title-bar Sparkles opens AI Panel bound to the note", async ({
    page,
  }) => {
    await bootstrapNotebookWithPage(page);
    await page.getByTestId("note-open-ai-panel").first().click();
    await expect(page.getByTestId("ai-panel-tab-ask")).toBeVisible();
    // Ask tab is the default.
    await expect(page.getByTestId("ai-panel-tab-ask")).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  test("sidebar AI icon opens AI Panel for the focused note", async ({
    page,
  }) => {
    await bootstrapNotebookWithPage(page);
    await page.getByTestId("sidebar-tab-ai_panel").click();
    await expect(page.getByTestId("ai-panel-tab-ask")).toBeVisible();
  });

  test("sidebar AI icon is a no-op when no note is focused", async ({
    page,
  }) => {
    await page.goto("/workspace/notebooks");
    await page.getByRole("button", { name: /create/i }).first().click();
    await page.waitForURL(/\/workspace\/notebooks\/[^/]+$/);
    // No page yet → no focused note.
    await page.getByTestId("sidebar-tab-ai_panel").click();
    await expect(page.getByTestId("ai-panel-tab-ask")).toHaveCount(0);
  });

  test("switching tabs swaps the body", async ({ page }) => {
    await bootstrapNotebookWithPage(page);
    await page.getByTestId("note-open-ai-panel").first().click();

    await page.getByTestId("ai-panel-tab-summary").click();
    await expect(page.getByTestId("ai-panel-summary")).toBeVisible();

    await page.getByTestId("ai-panel-tab-memory").click();
    // MemoryLinksPanel renders either the list or an empty-state hint.
    await expect(
      page.locator("text=/memory|No memories|empty/i").first(),
    ).toBeVisible();

    await page.getByTestId("ai-panel-tab-trace").click();
    await expect(page.getByTestId("ai-actions-list")).toBeVisible();
  });

  test("layout persists across reload", async ({ page }) => {
    await bootstrapNotebookWithPage(page);
    await page.getByTestId("note-open-ai-panel").first().click();
    await expect(page.getByTestId("ai-panel-tab-ask")).toBeVisible();

    const url = page.url();
    await page.reload();
    await page.waitForURL(url);

    // After reload the AI Panel window should still exist.
    await expect(page.getByTestId("ai-panel-tab-ask")).toBeVisible({
      timeout: 10_000,
    });
  });
});
