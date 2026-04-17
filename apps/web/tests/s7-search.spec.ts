import { test, expect } from "@playwright/test";

test.describe("S7 Search", () => {
  test("sidebar Search icon opens SearchWindow", async ({ page }) => {
    await page.goto("/workspace/notebooks");
    await page.getByRole("button", { name: /create/i }).first().click();
    await page.waitForURL(/\/workspace\/notebooks\/[^/]+$/);

    const searchTab = page.getByTestId("sidebar-tab-search");
    await expect(searchTab).toBeVisible();
    await searchTab.click();

    await expect(page.getByTestId("search-window")).toBeVisible();
    await expect(page.getByTestId("search-window-input")).toBeVisible();
  });
});
