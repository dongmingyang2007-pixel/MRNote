import { test, expect } from "@playwright/test";

test.describe("AI action trace tab", () => {
  test("trace tab of AI Panel shows an entry after a selection rewrite", async ({
    page,
  }) => {
    await page.goto("/workspace/notebooks");
    await page.getByRole("button", { name: /create/i }).first().click();
    await page.waitForURL(/\/workspace\/notebooks\/[^/]+$/);

    // Create a page inside the notebook.
    await page.getByRole("button", { name: /create/i }).first().click();

    // Type and rewrite.
    const editor = page.locator(".ProseMirror").first();
    await editor.click();
    await editor.type("Hello world, this is a sentence.");
    await editor.press("Meta+a");

    const rewrite = page.getByRole("button", { name: /rewrite/i });
    if (await rewrite.isVisible().catch(() => false)) {
      await rewrite.click();
      await page.waitForTimeout(2000);
    }

    // Open AI Panel from the note title-bar.
    await page.getByTestId("note-open-ai-panel").first().click();

    // Switch to the Trace tab and assert an entry is visible.
    await page.getByTestId("ai-panel-tab-trace").click();
    const items = page.getByTestId("ai-action-item");
    await expect(items.first()).toBeVisible({ timeout: 10_000 });
    await expect(items.first()).toContainText(/selection\.rewrite/);
  });
});
