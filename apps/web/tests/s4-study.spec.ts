import { test, expect } from "@playwright/test";

async function openNotebookWithStudyWindow(page: import("@playwright/test").Page) {
  await page.goto("/workspace/notebooks");
  await page.getByRole("button", { name: /create/i }).first().click();
  await page.waitForURL(/\/workspace\/notebooks\/[^/]+$/);
  // Open a page so the canvas has something; then click the sidebar "learn" icon
  // to open the Study window. The sidebar testid pattern is sidebar-tab-<id>.
  await page.getByRole("button", { name: /create/i }).first().click();
  await page.getByTestId("sidebar-tab-learn").click();
  await expect(page.getByTestId("study-window")).toBeVisible();
}

test.describe("S4 study loop", () => {
  test("create deck, add card, review Good, queue empty", async ({ page }) => {
    await openNotebookWithStudyWindow(page);
    await page.getByTestId("study-tab-decks").click();

    await page.locator('input[placeholder="New deck name"]').fill("Smoke deck");
    await page.getByTestId("decks-panel-create").click();
    await expect(page.getByTestId("deck-row")).toBeVisible();
    await page.getByTestId("deck-row").click();

    // CardsPanel — manual add.
    await page.locator('input[placeholder="Front"]').fill("Front Q");
    await page.locator('input[placeholder="Back"]').fill("Back A");
    await page.getByTestId("cards-panel-create").click();
    await expect(page.getByTestId("card-row")).toBeVisible();

    // Start review.
    await page.getByTestId("cards-panel-review").click();
    await expect(page.getByTestId("review-session")).toBeVisible();
    await expect(page.getByTestId("review-front")).toContainText("Front Q");

    // Reveal + Good.
    await page.getByTestId("review-reveal").click();
    await expect(page.getByTestId("review-back")).toContainText("Back A");
    await page.getByTestId("review-rate-3").click();

    // Queue empty state.
    await expect(page.getByTestId("review-empty")).toBeVisible({ timeout: 10_000 });
  });
});
