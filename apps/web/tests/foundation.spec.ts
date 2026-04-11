import { expect, test } from "@playwright/test";
import { installWorkbenchApiMock } from "./helpers/mockWorkbenchApi";

test.use({ locale: "zh-CN" });

test.describe("Foundation design system", () => {
  test("auth entry loads the shared font stack", async ({ page }) => {
    await page.goto("/login");
    const fontFamily = await page.evaluate(() => getComputedStyle(document.body).fontFamily);
    expect(fontFamily).toContain("Inter");
  });

  test("auth layout keeps the light surface tokens", async ({ page }) => {
    await page.goto("/login");
    const bgBase = await page.evaluate(() =>
      getComputedStyle(document.documentElement).getPropertyValue("--bg-base").trim(),
    );
    expect(["#fff", "#ffffff"]).toContain(bgBase.toLowerCase());
  });

  test("console applies the console theme when the session is authenticated", async ({ page }) => {
    await installWorkbenchApiMock(page, { authenticated: true });
    await page.goto("/app");
    const consoleShell = page.locator("[data-theme='console']").first();
    await expect(consoleShell).toBeVisible();
    await expect(page.locator("header.site-header-v2.is-console")).toBeVisible();
    await expect(page.getByRole("heading", { name: "我的 AI" })).toBeVisible();

    const bgBase = await page.evaluate(() =>
      getComputedStyle(document.querySelector("[data-theme='console']") as Element).getPropertyValue("--bg-base").trim(),
    );
    expect(bgBase).toBe("#f5f0eb");
  });

  test("unauthenticated console routes redirect with locale preserved", async ({ page }) => {
    await page.goto("/app");
    await expect(page).toHaveURL(/\/login\?next=/);

    await page.goto("/en/app");
    await expect(page).toHaveURL(/\/en\/login\?next=/);
  });

  test("deep-linked console login returns to the requested route", async ({ page }) => {
    await installWorkbenchApiMock(page);

    await page.goto("/en/app/chat");
    await expect(page).toHaveURL(/\/en\/login\?next=/);

    await page.locator("#login-email").fill("deep-link@example.com");
    await page.locator("#login-password").fill("password-1234");
    await page.locator("button[type='submit']").click();

    await expect(page).toHaveURL(/\/en\/app\/chat(?:\?|$)/);
    await expect(page.locator("[data-theme='console']").first()).toBeVisible();
  });

  test("default login lands on the assistants console route", async ({ page }) => {
    await installWorkbenchApiMock(page);

    await page.goto("/login");
    await page.locator("#login-email").fill("default-login@example.com");
    await page.locator("#login-password").fill("password-1234");
    await page.locator("button[type='submit']").click();

    await expect(page).toHaveURL(/\/app\/assistants$/);
    await expect(page.getByRole("heading", { name: "我的 AI" })).toBeVisible();
  });

  test("root entry redirects into the console login flow", async ({ page }) => {
    await page.goto("/", { waitUntil: "commit" });
    await expect(page).toHaveURL(/\/login\?next=/);
  });

});
