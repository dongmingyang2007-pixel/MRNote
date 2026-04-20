import { expect, test } from "@playwright/test";

test.describe("Google OAuth surface", () => {
  test("/login shows Google button above email form with OR divider", async ({
    page,
  }) => {
    await page.goto("/en/login");

    const button = page.getByTestId("google-signin-link");
    await expect(button).toBeVisible();
    await expect(page.locator(".auth-divider")).toBeVisible();

    const emailInput = page.locator('input[type="email"]').first();
    await expect(emailInput).toBeVisible();

    const buttonBox = await button.boundingBox();
    const emailBox = await emailInput.boundingBox();
    expect(buttonBox && emailBox).toBeTruthy();
    if (buttonBox && emailBox) {
      expect(buttonBox.y).toBeLessThan(emailBox.y);
    }
  });

  test("/register shows Google button on the initial form step", async ({
    page,
  }) => {
    await page.goto("/en/register");
    await expect(page.getByTestId("google-signin-link")).toBeVisible();
  });

  test("Google button href carries mode=signin and next", async ({ page }) => {
    await page.goto("/en/login?next=/app/notebooks/abc");
    const href = await page
      .getByTestId("google-signin-link")
      .getAttribute("href");
    expect(href).toContain("/api/v1/auth/google/authorize");
    expect(href).toContain("mode=signin");
    expect(href).toContain("next=%2Fapp%2Fnotebooks%2Fabc");
  });

  test("/app/settings shows Connect Google when not linked", async ({
    page,
  }) => {
    // Only runs when the harness provides an authenticated session; the
    // settings page redirects to /login otherwise. Skipped locally by default.
    test.skip(
      !process.env.PLAYWRIGHT_AUTH_EMAIL,
      "requires logged-in fixture",
    );
    await page.goto("/en/app/settings");
    await expect(page.getByTestId("oauth-connect-google")).toBeVisible();
  });
});
