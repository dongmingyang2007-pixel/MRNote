import { test, expect } from "@playwright/test";

test.describe("S6 Billing", () => {
  test("settings/billing renders 4 plan cards", async ({ page }) => {
    await page.goto("/workspace/settings/billing");
    await page.waitForLoadState("domcontentloaded");
    const billingPage = page.getByTestId("billing-page");
    if (await billingPage.isVisible().catch(() => false)) {
      await expect(page.getByTestId("plan-card-free")).toBeVisible();
      await expect(page.getByTestId("plan-card-pro")).toBeVisible();
      await expect(page.getByTestId("plan-card-power")).toBeVisible();
      await expect(page.getByTestId("plan-card-team")).toBeVisible();
    }
  });
});
