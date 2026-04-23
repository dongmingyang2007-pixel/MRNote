import { test, expect } from "@playwright/test";
import path from "node:path";

// S9 — Upload PDF → study asset ingest → auto overview page (spec §22.2)
//
// Flow under test:
// 1. User opens a notebook and chooses "upload" from the canvas/sidebar.
// 2. They pick a small PDF (apps/web/tests/fixtures/sample.pdf).
// 3. Backend accepts the upload, the StudyAsset ingest pipeline chunks
//    + embeds + auto-creates an overview page.
// 4. The notebook's page list now contains a page titled something like
//    `"<title> 概览"` or "<title> Overview".
//
// Dependencies the dev stack needs to have online for the assertion to
// pass end-to-end:
// - S3 / local storage wired up
// - Celery worker running `study_asset_ingest_task` in eager mode OR
//   backgrounded; the test uses a generous timeout.
// - The A5 work that exposes `POST /api/v1/study-assets` and seeds
//   overview pages via `_upsert_generated_page`.
//
// This repo does NOT configure Celery eager mode by default, and the
// file-upload button is behind a sidebar flow that the test environment
// may not render. Until A5 ships the final endpoint + the dev server
// starts a worker, we `test.skip` with a clear pointer.

test.describe("S9 Upload PDF → auto-ingest", () => {
  test("uploading a small PDF creates an overview page", async ({ page }) => {
    test.skip(
      !process.env.PLAYWRIGHT_STUDY_INGEST_LIVE,
      "TODO: requires S3 + Celery worker running study_asset_ingest_task. "
        + "Also waits on A5's /api/v1/study-assets upload endpoint surface. "
        + "Set PLAYWRIGHT_STUDY_INGEST_LIVE=1 once both are wired.",
    );

    await page.goto("/workspace/notebooks");
    await page.getByRole("button", { name: /create/i }).first().click();
    await page.waitForURL(/\/workspace\/notebooks\/[^/]+$/);

    // Find the upload button — the sidebar or canvas toolbar should
    // expose a hidden file input with data-testid `upload-pdf-input`.
    const uploadInput = page.getByTestId("upload-pdf-input");
    await expect(uploadInput).toBeAttached({ timeout: 10_000 });

    const pdfPath = path.resolve(
      __dirname,
      "fixtures",
      "sample.pdf",
    );
    await uploadInput.setInputFiles(pdfPath);

    // Wait for the overview page to appear in the page list. The page
    // title includes the asset's title; our fixture is titled "sample".
    const overview = page.getByRole("link", { name: /sample.*(overview|概览)/i });
    await expect(overview).toBeVisible({ timeout: 60_000 });
  });
});
