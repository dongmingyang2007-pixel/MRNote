import { expect, test, type Page, type Route } from "@playwright/test";

test.use({ locale: "zh-CN" });

const NOTEBOOK_ID = "nb-references-test";
const APP_ORIGIN = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3100";

function loopbackOrigins(origin: string): string[] {
  try {
    const url = new URL(origin);
    if (url.hostname !== "localhost" && url.hostname !== "127.0.0.1") {
      return [origin];
    }
    const variants = ["localhost", "127.0.0.1"].map((hostname) => {
      const next = new URL(origin);
      next.hostname = hostname;
      return next.origin;
    });
    return Array.from(new Set(variants));
  } catch {
    return [origin];
  }
}

const COOKIE_ORIGINS = loopbackOrigins(APP_ORIGIN);

interface MockAsset {
  id: string;
  notebook_id: string;
  data_item_id?: string | null;
  title: string;
  asset_type: string;
  status: string;
  total_chunks: number;
  tags: string[];
  created_at: string;
}

const SEEDED_ASSETS: MockAsset[] = [
  {
    id: "asset-1",
    notebook_id: NOTEBOOK_ID,
    data_item_id: "di-1",
    title: "Quantum Mechanics",
    asset_type: "pdf",
    status: "indexed",
    total_chunks: 12,
    tags: ["physics"],
    created_at: "2026-03-14T12:00:00.000Z",
  },
  {
    id: "asset-2",
    notebook_id: NOTEBOOK_ID,
    data_item_id: "di-2",
    title: "MyNotes.md",
    asset_type: "article",
    status: "pending",
    total_chunks: 0,
    tags: [],
    created_at: "2026-03-14T12:00:00.000Z",
  },
];

async function setAuthCookies(page: Page): Promise<void> {
  await page.context().addCookies(
    COOKIE_ORIGINS.flatMap((origin) => [
      {
        name: "auth_state",
        value: "1",
        url: origin,
        sameSite: "Lax" as const,
      },
      {
        name: "access_token",
        value: "playwright-access-token",
        url: origin,
        httpOnly: true,
        sameSite: "Lax" as const,
      },
      {
        name: "mrnote_workspace_id",
        value: "ws-playwright",
        url: origin,
        sameSite: "Lax" as const,
      },
    ]),
  );
}

async function fulfillJson(
  route: Route,
  payload: unknown,
  status = 200,
): Promise<void> {
  const request = route.request();
  const origin = request.headers()["origin"] || APP_ORIGIN;
  await route.fulfill({
    status,
    contentType: "application/json",
    headers: {
      "access-control-allow-origin": origin,
      "access-control-allow-credentials": "true",
      "access-control-allow-methods":
        "GET,POST,PUT,PATCH,DELETE,OPTIONS",
      "access-control-allow-headers":
        request.headers()["access-control-request-headers"] ||
        "content-type,x-csrf-token,x-workspace-id",
      vary: "Origin",
    },
    body: JSON.stringify(payload),
  });
}

async function openReferencesWindow(page: Page): Promise<void> {
  // The references window is opened by clicking its sidebar tab. The
  // collapsed `glass-sidebar` is fixed at the viewport edge inside the
  // notebook layout; the tab carries `data-testid="sidebar-tab-references"`.
  const tab = page.getByTestId("sidebar-tab-references");
  await tab.waitFor({ state: "visible", timeout: 15000 });
  await tab.click();
}

async function installApiMocks(
  page: Page,
  options: { assets?: MockAsset[] } = {},
): Promise<void> {
  const assets = options.assets ?? SEEDED_ASSETS;

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const { pathname } = url;
    const method = request.method().toUpperCase();

    if (method === "OPTIONS") {
      const origin = request.headers()["origin"] || APP_ORIGIN;
      await route.fulfill({
        status: 204,
        headers: {
          "access-control-allow-origin": origin,
          "access-control-allow-credentials": "true",
          "access-control-allow-methods":
            "GET,POST,PUT,PATCH,DELETE,OPTIONS",
          "access-control-allow-headers":
            request.headers()["access-control-request-headers"] ||
            "content-type,x-csrf-token,x-workspace-id",
          "access-control-max-age": "600",
          vary: "Origin",
        },
        body: "",
      });
      return;
    }

    if (pathname === "/api/v1/auth/csrf" && method === "GET") {
      await fulfillJson(route, { csrf_token: "csrf-playwright-token" });
      return;
    }

    if (pathname === "/api/v1/auth/me" && method === "GET") {
      await fulfillJson(route, {
        id: "user-playwright",
        email: "playwright@example.com",
        display_name: "Playwright User",
        persona: "researcher",
        workspace_id: "ws-playwright",
      });
      return;
    }

    if (pathname === `/api/v1/notebooks/${NOTEBOOK_ID}` && method === "GET") {
      await fulfillJson(route, {
        id: NOTEBOOK_ID,
        title: "References Library Test Notebook",
        project_id: "proj-references-test",
        workspace_id: "ws-playwright",
        created_at: "2026-03-14T12:00:00.000Z",
        updated_at: "2026-03-14T12:00:00.000Z",
      });
      return;
    }

    if (
      pathname === `/api/v1/notebooks/${NOTEBOOK_ID}/study-assets` &&
      method === "GET"
    ) {
      await fulfillJson(route, { items: assets });
      return;
    }

    if (
      pathname === `/api/v1/notebooks/${NOTEBOOK_ID}/pages` &&
      method === "GET"
    ) {
      await fulfillJson(route, { items: [] });
      return;
    }

    if (pathname === "/api/v1/projects" && method === "GET") {
      await fulfillJson(route, {
        items: [
          {
            id: "proj-references-test",
            name: "Test project",
          },
        ],
      });
      return;
    }

    // Digest drawer endpoints — return 404 so the drawer renders nothing
    // instead of crashing on `digest.blocks.slice(...)`.
    if (pathname.startsWith("/api/v1/digest/")) {
      await fulfillJson(
        route,
        { error: { code: "not_found", message: "no digest" } },
        404,
      );
      return;
    }

    // Allow other unhandled GETs to soft-fail with empty bodies so the
    // page doesn't blow up on incidental fetches.
    if (method === "GET") {
      await fulfillJson(route, { items: [] });
      return;
    }

    // POST/PATCH/DELETE we don't care about: 200 with empty body.
    await fulfillJson(route, {});
  });

  // Marketing/digest endpoints live under /api/v1 already; no extra routes
  // needed.
}

async function setupReferencesPage(
  page: Page,
  options: { assets?: MockAsset[] } = {},
): Promise<void> {
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      console.log("[browser-error]", msg.text());
    }
  });
  page.on("pageerror", (err) => {
    console.log("[page-error]", err.message);
  });
  await setAuthCookies(page);
  await installApiMocks(page, options);
  await page.goto(`/zh/app/notebooks/${NOTEBOOK_ID}`);
  await openReferencesWindow(page);
  // The references window is dynamic-imported; wait until its content has
  // mounted (either the create button is visible, or the empty state renders).
  await page.waitForSelector(
    '[data-testid="references-create-button"], .reference-library-window__empty',
    { timeout: 15000 },
  );
}

test.describe("References library window", () => {
  test("renders seeded study assets with status, tags, and search controls", async ({
    page,
  }) => {
    await setupReferencesPage(page);

    const cards = page.getByTestId("reference-asset-card");
    await expect(cards).toHaveCount(2);

    const quantumCard = cards.filter({ hasText: "Quantum Mechanics" });
    await expect(quantumCard).toBeVisible();
    // "已完成" is the Chinese label for `indexed`.
    await expect(quantumCard).toContainText("已完成");

    // Tag chip on the card itself.
    await expect(
      quantumCard.locator(".reference-library-window__tag-chip"),
    ).toHaveText("physics");

    // Filter pill at the top.
    const physicsPill = page.getByTestId("references-tag-filter").filter({
      hasText: "physics",
    });
    await expect(physicsPill).toBeVisible();

    // Search input present with placeholder.
    const search = page.getByTestId("references-search");
    await expect(search).toBeVisible();
    await expect(search).toHaveAttribute("placeholder", /搜索/);
  });

  test("clicking the physics tag filter narrows the list to matching assets", async ({
    page,
  }) => {
    await setupReferencesPage(page);

    await expect(page.getByTestId("reference-asset-card")).toHaveCount(2);

    await page
      .getByTestId("references-tag-filter")
      .filter({ hasText: "physics" })
      .click();

    const remainingCards = page.getByTestId("reference-asset-card");
    await expect(remainingCards).toHaveCount(1);
    await expect(remainingCards.first()).toContainText("Quantum Mechanics");
    await expect(page.getByText("MyNotes.md", { exact: false })).toHaveCount(0);
  });

  test("create button opens a menu listing all four document types", async ({
    page,
  }) => {
    await setupReferencesPage(page);

    const trigger = page.getByTestId("references-create-button");
    await expect(trigger).toBeVisible();
    await trigger.click();

    const menu = page.getByTestId("references-create-menu");
    await expect(menu).toBeVisible();
    await expect(page.getByTestId("references-create-docx")).toBeVisible();
    await expect(page.getByTestId("references-create-xlsx")).toBeVisible();
    await expect(page.getByTestId("references-create-pptx")).toBeVisible();
    await expect(page.getByTestId("references-create-pdf")).toBeVisible();

    // Click outside (on the page body, well clear of the menu) to dismiss.
    await page.mouse.click(5, 5);
    await expect(menu).toHaveCount(0);
  });

  test("search input filters cards by title prefix", async ({ page }) => {
    await setupReferencesPage(page);

    await expect(page.getByTestId("reference-asset-card")).toHaveCount(2);

    await page.getByTestId("references-search").fill("myno");

    const cards = page.getByTestId("reference-asset-card");
    await expect(cards).toHaveCount(1);
    await expect(cards.first()).toContainText("MyNotes.md");
    await expect(page.getByText("Quantum Mechanics", { exact: false })).toHaveCount(0);
  });
});
