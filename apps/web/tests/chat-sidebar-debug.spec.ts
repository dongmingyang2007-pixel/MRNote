import { expect, test } from "@playwright/test";
import { installWorkbenchApiMock } from "./helpers/mockWorkbenchApi";

test.use({ locale: "zh-CN" });

function measureChatLayout() {
  const rect = (element: Element | null) => {
    if (!element) {
      return null;
    }
    const box = element.getBoundingClientRect();
    const style = window.getComputedStyle(element);
    return {
      x: Math.round(box.x),
      y: Math.round(box.y),
      width: Math.round(box.width),
      height: Math.round(box.height),
      position: style.position,
      transform: style.transform,
      zIndex: style.zIndex,
    };
  };

  const menu = document.querySelector(".chat-sidebar-context-menu");
  const composer = document.querySelector(".chat-input-bar");
  const menuButton =
    document.querySelector(".chat-sidebar-context-item.is-danger");
  let menuHitTarget: string | null = null;

  if (menuButton) {
    const box = menuButton.getBoundingClientRect();
    const hit = document.elementFromPoint(
      box.left + box.width / 2,
      box.top + box.height / 2,
    );
    menuHitTarget =
      hit?.closest(".chat-sidebar-context-menu")?.className || hit?.className || null;
  }

  return {
    sidebar: rect(document.querySelector(".chat-sidebar")),
    main: rect(document.querySelector(".chat-main")),
    layout: rect(document.querySelector(".chat-page-layout.chat-page")),
    menu: rect(menu),
    composer: rect(composer),
    menuHitTarget,
  };
}

test("debug chat sidebar double click geometry", async ({ page }) => {
  const handle = await installWorkbenchApiMock(page, { authenticated: true });

  await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
  await expect(page.locator(".chat-sidebar-item").first()).toBeVisible();

  const before = await page.evaluate(measureChatLayout);
  await page.locator(".chat-sidebar-item").first().dblclick();
  await page.waitForTimeout(150);
  const afterItemDblClick = await page.evaluate(measureChatLayout);

  await page
    .locator(".glass-sidebar--collapsed .glass-sidebar-nav-item")
    .nth(1)
    .dblclick();
  await page.waitForTimeout(300);
  const afterNavDblClick = await page.evaluate(measureChatLayout);

  await page.locator(".chat-sidebar-item").first().click({ button: "right" });
  await page.waitForTimeout(150);
  const afterContextMenu = await page.evaluate(measureChatLayout);

  console.log(
    JSON.stringify(
      {
        before,
        afterItemDblClick,
        afterNavDblClick,
        afterContextMenu,
      },
      null,
      2,
    ),
  );

  expect(page.locator(".chat-sidebar")).toBeVisible();
});
