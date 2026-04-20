import { expect, test } from "@playwright/test";

test.use({ locale: "zh-CN" });

test.describe("Role-personalized landing", () => {
  test.beforeEach(async ({ context }) => {
    await context.clearCookies();
  });

  test("empty state shows chips + placeholders, clicking a chip reveals content", async ({ page }) => {
    await page.goto("/");

    // Section is present with empty state.
    const section = page.locator("section.marketing-exclusive");
    await expect(section).toBeVisible();
    await expect(section.getByText("选择你的身份，解锁定制内容")).toBeVisible();

    // Pick 研究生
    await section.getByRole("radio", { name: "研究生" }).click();

    // Populated content visible
    await expect(section.getByText("文献综述自动整理")).toBeVisible();
    await expect(section.getByText("研究生 5 件套")).toBeVisible();
    await expect(section.getByText(".edu 邮箱 · Pro 免费 6 月")).toBeVisible();

    // Hero badge appears with the role label
    await expect(page.getByTestId("hero-role-badge")).toContainText("研究生");

    // Cookie persisted
    const cookies = await page.context().cookies();
    const roleCookie = cookies.find((c) => c.name === "mrai_landing_role");
    expect(roleCookie?.value).toBe("researcher");
  });

  test("switching to a different role swaps the content", async ({ page }) => {
    await page.goto("/");
    const section = page.locator("section.marketing-exclusive");
    await section.getByRole("radio", { name: "研究生" }).click();
    await expect(section.getByText("文献综述自动整理")).toBeVisible();

    await section.getByRole("radio", { name: "律师" }).click();
    await expect(section.getByText("合同摘要 10 秒出")).toBeVisible();
    await expect(section.getByText("文献综述自动整理")).toHaveCount(0);
  });

  test("switch button clears the role and returns to empty state", async ({ page }) => {
    await page.goto("/");
    const section = page.locator("section.marketing-exclusive");
    await section.getByRole("radio", { name: "医生" }).click();
    await expect(section.getByText("门诊随手记结构化")).toBeVisible();

    await section.getByRole("button", { name: "切换" }).click();
    await expect(section.getByText("选择你的身份，解锁定制内容")).toBeVisible();
    await expect(page.getByTestId("hero-role-badge")).toHaveCount(0);
  });

  test("returning visitor sees their role on reload (SSR hydration)", async ({ page }) => {
    await page.goto("/");
    const section = page.locator("section.marketing-exclusive");
    await section.getByRole("radio", { name: "创业者" }).click();
    await expect(section.getByText("客户访谈自动提炼洞察")).toBeVisible();

    await page.reload();
    await expect(page.getByTestId("hero-role-badge")).toContainText("创业者");
    await expect(section.getByText("客户访谈自动提炼洞察")).toBeVisible();
  });
});
