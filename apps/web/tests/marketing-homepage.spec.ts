import { expect, test } from "@playwright/test";

/**
 * Marketing homepage smoke — proves the mocks render and the
 * live-canvas hint is visible. Intentionally not a full visual
 * regression suite; visual changes can pass silently.
 *
 * Routing note: next-intl is configured with localePrefix "as-needed"
 * and defaultLocale "zh", so the Chinese landing page is served at
 * "/" rather than "/zh". We follow the same bare-path convention as
 * smoke.spec.ts / foundation.spec.ts and scope the locale via
 * test.use({ locale: "zh-CN" }).
 */
test.use({ locale: "zh-CN" });

test.describe("Marketing homepage", () => {
  test("renders hero canvas stage + all nine mocks", async ({ page }) => {
    await page.goto("/");

    // Hero h1 — sanity check the page rendered.
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

    // Hero canvas stage — three MockWindow chromes inside it.
    const stage = page.locator(".marketing-canvas-stage");
    await expect(stage).toBeVisible();
    await expect(stage.locator(".marketing-mock")).toHaveCount(3);

    // Per-container scoped counts. We intentionally assert per container
    // rather than a single total — the mobile fallback inside
    // LiveCanvasDemo renders 3 additional mocks that are hidden via CSS
    // on desktop, so a page-wide total would double-count them. Scoping
    // also makes the assertions robust to future DOM shuffles.
    await expect(
      page.locator(".marketing-feature-row__media .marketing-mock"),
    ).toHaveCount(3);
    await expect(
      page.locator(".marketing-live-canvas .marketing-mock"),
    ).toHaveCount(3);

    // Live canvas hint pill.
    await expect(
      page.locator(".marketing-live-canvas__hint"),
    ).toBeVisible();
  });

  test("auth page shows back-to-home link", async ({ page }) => {
    await page.goto("/login");
    const backLink = page.getByRole("link", { name: /返回首页/ });
    await expect(backLink).toBeVisible();
    await backLink.click();
    await expect(page).toHaveURL(/\/$/);
  });
});
