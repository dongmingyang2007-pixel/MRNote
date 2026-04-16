import { test, expect } from "@playwright/test";

test.describe("AI action trace panel", () => {
  test("shows an entry after a selection rewrite", async ({ page }) => {
    await page.goto("/workspace/notebooks");
    // Create a notebook
    await page.getByRole("button", { name: /create/i }).first().click();
    await page.waitForURL(/\/workspace\/notebooks\/[^/]+$/);

    // Create a page
    await page.getByRole("button", { name: /create/i }).first().click();

    // Type into the editor, select all, run rewrite
    const editor = page.locator(".ProseMirror").first();
    await editor.click();
    await editor.type("Hello world, this is a sentence.");
    await editor.press("Meta+a");

    const rewrite = page.getByRole("button", { name: /rewrite/i });
    if (await rewrite.isVisible().catch(() => false)) {
      await rewrite.click();
      await page.waitForTimeout(2000);
    }

    // Switch to trace tab
    await page.getByTestId("panel-tab-trace").click();

    // Expect at least one entry
    const items = page.getByTestId("ai-action-item");
    await expect(items.first()).toBeVisible({ timeout: 10_000 });
    await expect(items.first()).toContainText(/selection\.rewrite/);
  });
});
