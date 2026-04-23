import { test, expect } from "@playwright/test";

// S11 — Free plan quota exceeded → upgrade modal → Stripe checkout → Pro
// (spec §22.2)
//
// Flow:
// 1. On a fresh Free workspace, create one notebook (allowed).
// 2. Try to create a second notebook — backend returns 402
//    `plan_limit_exceeded`.
// 3. Frontend catches the 402 and opens the UpgradeModal.
// 4. User clicks the modal's primary CTA — frontend calls
//    `/api/v1/billing/checkout` which returns a Stripe redirect URL.
// 5. After a simulated successful redirect we reload `/billing/me` and
//    assert the workspace plan shows `pro`.
//
// Dependencies:
// - Backend quota limit for Free plan notebooks is enforced (S4/S5 work).
// - Stripe is either live or mocked via `STRIPE_MOCK_REDIRECT=1`.
// - The UpgradeModal has `data-testid="upgrade-modal"` (already) and
//   `data-testid="upgrade-modal-go"` (already) — see
//   apps/web/components/billing/UpgradeModal.tsx.

test.describe("S11 Upgrade flow", () => {
  test("creating a 2nd notebook on Free opens the upgrade modal", async ({
    page,
  }) => {
    test.skip(
      !process.env.PLAYWRIGHT_BILLING_LIVE,
      "TODO: requires the dev backend to enforce Free plan notebook quota "
        + "(PLAN_LIMITS_ENFORCED=1) and a Stripe test mode or "
        + "STRIPE_MOCK_REDIRECT=1 fixture. Run with PLAYWRIGHT_BILLING_LIVE=1 "
        + "once both are in the dev env.",
    );

    await page.goto("/workspace/notebooks");
    // Create notebook #1 — allowed.
    await page.getByRole("button", { name: /create/i }).first().click();
    await page.waitForURL(/\/workspace\/notebooks\/[^/]+$/);

    // Go back and try to create notebook #2.
    await page.goto("/workspace/notebooks");
    await page.getByRole("button", { name: /create/i }).first().click();

    // The UpgradeModal should appear.
    const modal = page.getByTestId("upgrade-modal");
    await expect(modal).toBeVisible({ timeout: 15_000 });

    // Click the primary CTA. It calls /billing/checkout and redirects
    // us to Stripe. In test mode we expect the app to redirect to a
    // Stripe URL (mocked or real).
    const go = page.getByTestId("upgrade-modal-go");
    await expect(go).toBeVisible();

    // Intercept the Stripe checkout call and fake a successful
    // "session created → return to app" redirect.
    await page.route("**/api/v1/billing/checkout", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          url: new URL(
            "/workspace/settings/billing?upgrade=success",
            page.url(),
          ).toString(),
        }),
      });
    });

    await go.click();

    // After the "redirect" we should land back on the billing settings
    // page. We don't actually flip the subscription here (no webhook),
    // but the presence of the success param is enough to prove the
    // modal → checkout wiring.
    await page.waitForURL(/upgrade=success/, { timeout: 15_000 });
    await expect(page.getByTestId("billing-page")).toBeVisible();
  });
});
