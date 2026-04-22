import { expect, test } from "@playwright/test";

// Landing `/` should remain visible to logged-in users; the header just
// swaps its CTA area from "login / register" to "open workspace + avatar".

test.describe("Landing logged-in header", () => {
  test("logged-in user can view the landing page and sees the open-workspace CTA (zh)", async ({
    page,
    context,
  }) => {
    // Seed an auth_state cookie for localhost:3000.
    await context.addCookies([
      {
        name: "auth_state",
        value: "1",
        domain: "localhost",
        path: "/",
        httpOnly: false,
        secure: false,
        sameSite: "Lax",
      },
    ]);

    await page.goto("/");
    await expect(page).toHaveURL(/\/zh$|\/$/);
    const header = page.getByTestId("marketing-header");
    await expect(header).toBeVisible();

    const openWorkspace = header.getByRole("link", { name: "进入工作台" });
    await expect(openWorkspace).toBeVisible();
    await expect(openWorkspace).toHaveAttribute("href", /\/app$/);

    await expect(page.getByTestId("marketing-user-menu")).toBeVisible();

    // Logged-out CTA should not appear in the header.
    await expect(header.getByRole("link", { name: "登录", exact: true })).toHaveCount(0);
  });

  test("logged-out user still sees login + register CTAs (zh)", async ({
    page,
  }) => {
    await page.goto("/");
    const header = page.getByTestId("marketing-header");
    await expect(header.getByRole("link", { name: "登录", exact: true })).toBeVisible();
    await expect(header.getByRole("link", { name: "免费开始", exact: true })).toBeVisible();
    await expect(page.getByTestId("marketing-user-menu")).toHaveCount(0);
  });

  test("en locale renders English header labels for logged-in user", async ({
    page,
    context,
  }) => {
    await context.addCookies([
      {
        name: "auth_state",
        value: "1",
        domain: "localhost",
        path: "/",
        httpOnly: false,
        secure: false,
        sameSite: "Lax",
      },
    ]);

    await page.goto("/en");
    const header = page.getByTestId("marketing-header");
    await expect(header.getByRole("link", { name: "Open workspace" })).toBeVisible();
    await expect(page.getByTestId("marketing-user-menu")).toBeVisible();
  });
});
