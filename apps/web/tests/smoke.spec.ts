import { expect, Page, test } from "@playwright/test";
import { installWorkbenchApiMock } from "./helpers/mockWorkbenchApi";

test.use({ locale: "zh-CN" });

async function fillRegisterForm(
  page: Page,
  localePrefix: "" | "/en",
  stamp: string,
) {
  await page.goto(`${localePrefix}/register`);
  await page.locator("#register-display-name").fill(`User ${stamp}`);
  await page.locator("#register-email").fill(`user-${stamp}@example.com`);
  await page.locator("#register-password").fill("password-1234");
  await page.locator("#register-confirm-password").fill("password-1234");
}

test("root entry renders the public marketing homepage for guests", async ({
  page,
}) => {
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({
        error: {
          code: "unauthorized",
          message: "Authentication required",
        },
      }),
    }),
  );
  await page.route("**/api/v1/digest/**", (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({
        error: {
          code: "unauthorized",
          message: "Authentication required",
        },
      }),
    }),
  );

  await page.goto("/");
  await expect(page).toHaveURL(/\/zh$|\/$/);
  await expect(page.getByTestId("marketing-header")).toBeVisible();
  await expect(
    page.getByRole("link", { name: "登录", exact: true }),
  ).toBeVisible();
  await page.waitForTimeout(1400);
  await expect(page).not.toHaveURL(/\/login/);
});

test("english register flow uses two-step verification and enters the english console", async ({
  page,
}) => {
  await installWorkbenchApiMock(page);

  const stamp = `${Date.now()}-${Math.floor(Math.random() * 10000)}`;
  await fillRegisterForm(page, "/en", stamp);
  await page.getByRole("button", { name: "Get verification code" }).click();

  await expect(
    page.getByRole("heading", { name: "Check your email" }),
  ).toBeVisible();
  await page.locator("#register-code").fill("654321");
  await page
    .getByRole("button", { name: "Register and enter console" })
    .click();
  await expect(
    page.getByRole("heading", { name: "One more step." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Skip for now" }).click();

  await expect(page).toHaveURL(/\/en\/app$/);
  await expect(
    page.getByRole("heading", { name: "Continue from your workspace." }),
  ).toBeVisible();
  await expect(page.locator("[data-theme='console']").first()).toBeVisible();
});

test("chinese forgot-password flow uses verification code and shows success state", async ({
  page,
}) => {
  await installWorkbenchApiMock(page);

  await page.goto("/forgot-password");
  await page.locator("#reset-email").fill("reset@example.com");
  await page.getByRole("button", { name: "获取验证码" }).click();

  await expect(page.getByRole("heading", { name: "设置新密码" })).toBeVisible();
  await page.locator("#reset-code").fill("123456");
  await page.locator("#reset-password").fill("new-password-1234");
  await page.getByRole("button", { name: "确认重设" }).click();

  await expect(page.getByRole("heading", { name: "密码已更新" })).toBeVisible();
  await expect(
    page
      .getByRole("link", { name: "去登录" })
      .or(page.getByRole("button", { name: "去登录" })),
  ).toBeVisible();
});

test("console pages load correctly against mocked API", async ({ page }) => {
  await installWorkbenchApiMock(page, { authenticated: true });

  await page.goto("/app");
  await expect(page).toHaveURL(/\/app$/);
  await expect(
    page.getByRole("heading", { name: "今天从这里继续。" }),
  ).toBeVisible();

  await page.goto("/app/notebooks");
  await expect(
    page.getByRole("heading", { name: "笔记本库", exact: true }),
  ).toBeVisible();
});
