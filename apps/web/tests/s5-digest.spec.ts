import { test, expect } from "@playwright/test";

test.describe("S5 Proactive digest", () => {
  test("sidebar Bell opens DigestWindow", async ({ page }) => {
    // Minimal smoke: the Bell tab is visible on notebook sidebar,
    // and clicking it opens a digest window shell. Exercising the
    // full create → read → dismiss loop requires the dev stack with
    // Celery eager mode, which this repo doesn't configure by default.
    await page.goto("/workspace/notebooks");
    await page.getByRole("button", { name: /create/i }).first().click();
    await page.waitForURL(/\/workspace\/notebooks\/[^/]+$/);

    const bellTab = page.getByTestId("sidebar-tab-digest");
    await expect(bellTab).toBeVisible();
    await bellTab.click();

    await expect(page.getByTestId("digest-window")).toBeVisible();
  });
});
