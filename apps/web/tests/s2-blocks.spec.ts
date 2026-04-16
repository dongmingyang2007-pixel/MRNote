import { test, expect } from "@playwright/test";

async function openNewPage(page: import("@playwright/test").Page) {
  await page.goto("/workspace/notebooks");
  await page.getByRole("button", { name: /create/i }).first().click();
  await page.waitForURL(/\/workspace\/notebooks\/[^/]+$/);
  await page.getByRole("button", { name: /create/i }).first().click();
  await expect(page.locator(".ProseMirror").first()).toBeVisible();
}

test.describe("S2 block types", () => {
  test("flashcard block flips on click", async ({ page }) => {
    await openNewPage(page);
    const editor = page.locator(".ProseMirror").first();
    await editor.click();
    await editor.type("/flashcard");
    await page.keyboard.press("Enter");

    await expect(page.getByTestId("flashcard-block")).toBeVisible();

    await page.getByTestId("flashcard-front").fill("What is X?");
    await page.getByTestId("flashcard-back").fill("X is an answer.");
    await page.getByTestId("flashcard-mode-preview").click();

    const card = page.getByTestId("flashcard-card");
    await expect(card).toContainText(/What is X/);
    await card.click();
    await expect(card).toContainText(/X is an answer/);
  });

  test("task block toggle persists across reload", async ({ page }) => {
    await openNewPage(page);
    const editor = page.locator(".ProseMirror").first();
    await editor.click();
    await editor.type("/task");
    await page.keyboard.press("Enter");

    await expect(page.getByTestId("task-block")).toBeVisible();
    await page.locator(".task-block__title").fill("Ship S2");

    const checkbox = page.getByTestId("task-block-checkbox");
    await checkbox.check();
    await expect(checkbox).toBeChecked();

    await page.waitForTimeout(1500);
    await page.reload();
    await expect(page.getByTestId("task-block")).toBeVisible();
    await expect(page.getByTestId("task-block-checkbox")).toBeChecked();
  });
});
