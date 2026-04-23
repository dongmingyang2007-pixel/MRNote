import { test, expect } from "@playwright/test";

// S10 — Memory candidate extraction → confirm → link surfaces in panel
// (spec §22.2)
//
// Flow:
// 1. Open a page with some authored text.
// 2. Trigger memory extraction (either the "Extract memory" selection
//    action, or automatic via the page-edit pipeline).
// 3. Candidate cards render inside the AI Panel's Memory tab.
// 4. User clicks "Confirm" on one candidate — candidate becomes a
//    promoted Memory.
// 5. The MemoryLinksPanel (AI Panel "memory" tab) shows the new link.
//
// Dependencies:
// - The A5 NotebookSelectionMemoryLink bridge table has to be populated
//   by `/api/v1/pages/{id}/memory/confirm`. That's already wired.
// - An AI provider has to be configured so the extraction call returns
//   a non-empty set of candidates.
// - The MemoryLinksPanel renders candidates with the testids the
//   backend exposes (`memory-candidate-row`, `memory-candidate-confirm`).
//   If these aren't wired yet, this test will skip.

async function openNotebookAndPage(page: import("@playwright/test").Page) {
  await page.goto("/workspace/notebooks");
  await page.getByRole("button", { name: /create/i }).first().click();
  await page.waitForURL(/\/workspace\/notebooks\/[^/]+$/);
  await page.getByRole("button", { name: /create/i }).first().click();
  await expect(page.locator(".ProseMirror").first()).toBeVisible();
}

test.describe("S10 Memory links from page extraction", () => {
  test("confirm candidate → memory link appears in AI Panel", async ({
    page,
  }) => {
    test.skip(
      !process.env.PLAYWRIGHT_AI_LIVE,
      "TODO: requires a live AI backend. Memory-candidate extraction "
        + "calls the UnifiedMemoryPipeline which needs an LLM to return "
        + "candidate facts. Set PLAYWRIGHT_AI_LIVE=1 to run end-to-end.",
    );

    await openNotebookAndPage(page);
    const editor = page.locator(".ProseMirror").first();
    await editor.click();
    await editor.type(
      "I prefer dark mode. My favourite IDE is Zed. I usually code in Rust.",
    );
    await editor.press("Meta+a");

    // Kick off the extraction from the selection toolbar.
    const extract = page.getByTestId("ai-selection-action-extract_memory");
    await expect(extract).toBeVisible({ timeout: 10_000 });
    await extract.click();

    // Open the AI Panel memory tab and wait for a candidate row.
    await page.getByTestId("note-open-ai-panel").first().click();
    await page.getByTestId("ai-panel-tab-memory").click();

    const candidate = page.getByTestId("memory-candidate-row").first();
    await expect(candidate).toBeVisible({ timeout: 30_000 });

    // Confirm the first candidate.
    await page.getByTestId("memory-candidate-confirm").first().click();

    // After confirm, the link should show up in the memory-links list.
    const link = page.getByTestId("memory-link-row").first();
    await expect(link).toBeVisible({ timeout: 15_000 });
  });
});
