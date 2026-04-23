import { test, expect } from "@playwright/test";

// S8 — AI rewrite round-trip (spec §22.2)
//
// Scenario: user selects text in a notebook page → opens the AI
// selection menu → clicks "Rewrite" → a streaming AI panel returns a
// new draft → user clicks "Replace" (or the equivalent apply button)
// → the ProseMirror editor now contains the rewritten text.
//
// Dependencies:
// - Backend `/api/v1/ai/selection/rewrite` must stream a response
// - Frontend selection toolbar renders `ai-selection-action-rewrite`
//   (already shipped — see AISelectionActions.tsx)
// - The Replace button labels via `ai.actions.replace` and is the
//   primary button inside the `ai-selection-result` view.
//
// This test doesn't mock AI — it expects the dev server to be wired to
// a working AI provider. When the provider is stubbed out, the rewrite
// result may be empty; we assert only that the UI enters the
// "selection result" state, not the exact text. That matches S3/S7's
// smoke-test posture.

async function openNewPage(page: import("@playwright/test").Page) {
  await page.goto("/workspace/notebooks");
  await page.getByRole("button", { name: /create/i }).first().click();
  await page.waitForURL(/\/workspace\/notebooks\/[^/]+$/);
  await page.getByRole("button", { name: /create/i }).first().click();
  await expect(page.locator(".ProseMirror").first()).toBeVisible();
}

test.describe("S8 AI rewrite", () => {
  test("select → rewrite → apply replaces text", async ({ page }) => {
    test.skip(
      !process.env.PLAYWRIGHT_AI_LIVE,
      "TODO: requires a live AI backend provider (DASHSCOPE_API_KEY). "
        + "Set PLAYWRIGHT_AI_LIVE=1 to exercise the full rewrite loop.",
    );

    await openNewPage(page);
    const editor = page.locator(".ProseMirror").first();
    await editor.click();
    await editor.type("Hello world, this is a sentence to rewrite.");

    // Select all, then open the selection toolbar. The exact UX for
    // surfacing the toolbar lives in AISelectionActions; on desktop
    // it's auto-mounted beside the selection.
    await editor.press("Meta+a");
    const rewriteAction = page.getByTestId("ai-selection-action-rewrite");
    await expect(rewriteAction).toBeVisible({ timeout: 10_000 });
    await rewriteAction.click();

    // The streaming result view renders with data-testid
    // `ai-selection-structural` for structural outputs and a plain
    // `.ai-selection-result` wrapper for text outputs. Wait for either.
    await expect(
      page.locator(".ai-selection-result").first(),
    ).toBeVisible({ timeout: 30_000 });

    // Apply by clicking the primary button in the result footer.
    const applyBtn = page.locator(".ai-selection-result .mem-action-btn.is-primary");
    await applyBtn.click();

    // Editor content should change — at minimum the apply should have
    // closed the AI selection view.
    await expect(page.locator(".ai-selection-result")).toHaveCount(0);
  });
});
