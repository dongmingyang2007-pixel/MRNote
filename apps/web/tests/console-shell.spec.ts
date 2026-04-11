import { expect, test, type Page } from "@playwright/test";
import { installWorkbenchApiMock } from "./helpers/mockWorkbenchApi";

test.use({ locale: "zh-CN" });

async function stubBrowserVoiceApis(page: Page) {
  await page.addInitScript(() => {
    Object.defineProperty(HTMLMediaElement.prototype, "play", {
      configurable: true,
      value() {
        return Promise.resolve();
      },
    });

    Object.defineProperty(HTMLMediaElement.prototype, "pause", {
      configurable: true,
      value() {
        return undefined;
      },
    });

    class MockMediaRecorder {
      static isTypeSupported() {
        return true;
      }

      state = "inactive";
      mimeType: string;
      ondataavailable: ((event: { data: Blob }) => void) | null = null;
      onstop: (() => void) | null = null;
      stream = {
        getTracks: () => [{ stop() {} }],
      };

      constructor(
        stream: { getTracks: () => Array<{ stop: () => void }> },
        options?: { mimeType?: string },
      ) {
        this.stream = stream;
        this.mimeType = options?.mimeType || "audio/webm";
      }

      start() {
        this.state = "recording";
      }

      stop() {
        this.state = "inactive";
        this.ondataavailable?.({
          data: new Blob(["mock-audio"], { type: this.mimeType }),
        });
        this.onstop?.();
      }
    }

    Object.defineProperty(window, "MediaRecorder", {
      configurable: true,
      writable: true,
      value: MockMediaRecorder,
    });

    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: async () => ({
          getTracks: () => [{ stop() {} }],
        }),
      },
    });
  });
}

async function stubRealtimeDictationApis(page: Page) {
  await page.addInitScript(() => {
    class MockMediaStreamSource {
      connect() {
        return undefined;
      }
    }

    class MockScriptProcessor {
      onaudioprocess:
        | ((event: {
            inputBuffer: { getChannelData: () => Float32Array };
          }) => void)
        | null = null;

      connect() {
        return undefined;
      }

      disconnect() {
        return undefined;
      }
    }

    class MockGainNode {
      gain = { value: 1 };

      connect() {
        return undefined;
      }

      disconnect() {
        return undefined;
      }
    }

    class MockAudioContext {
      state: "running" | "suspended" | "closed" = "running";
      destination = {};

      resume() {
        this.state = "running";
        return Promise.resolve();
      }

      close() {
        this.state = "closed";
        return Promise.resolve();
      }

      createMediaStreamSource() {
        return new MockMediaStreamSource();
      }

      createScriptProcessor(bufferSize?: number) {
        (
          window as Window & { __lastDictationBufferSize?: number }
        ).__lastDictationBufferSize = bufferSize;
        return new MockScriptProcessor();
      }

      createGain() {
        return new MockGainNode();
      }
    }

    Object.defineProperty(window, "AudioContext", {
      configurable: true,
      writable: true,
      value: MockAudioContext,
    });

    Object.defineProperty(globalThis, "AudioContext", {
      configurable: true,
      writable: true,
      value: MockAudioContext,
    });

    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: async () => ({
          getTracks: () => [{ stop() {} }],
        }),
      },
    });

    class MockWebSocket {
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSING = 2;
      static readonly CLOSED = 3;

      isDictationSocket = false;
      readyState = MockWebSocket.CONNECTING;
      binaryType = "blob";
      onopen: ((event: unknown) => void) | null = null;
      onmessage: ((event: { data: string | ArrayBuffer }) => void) | null =
        null;
      onclose: ((event: { code: number; reason: string }) => void) | null =
        null;
      onerror: ((event: unknown) => void) | null = null;

      constructor(url: string) {
        this.isDictationSocket = url.includes("/api/v1/realtime/dictate");
        setTimeout(() => {
          this.readyState = MockWebSocket.OPEN;
          this.onopen?.({});
        }, 0);
      }

      send(data: string | ArrayBuffer) {
        if (!this.isDictationSocket) {
          return;
        }
        if (typeof data !== "string") {
          return;
        }
        const payload = JSON.parse(data);
        if (payload.type === "session.start") {
          setTimeout(() => {
            this.onmessage?.({
              data: JSON.stringify({ type: "session.ready" }),
            });
          }, 0);
          setTimeout(() => {
            this.onmessage?.({
              data: JSON.stringify({
                type: "transcript.partial",
                text: "帮我",
              }),
            });
          }, 50);
          return;
        }
        if (payload.type === "audio.stop") {
          setTimeout(() => {
            this.onmessage?.({
              data: JSON.stringify({
                type: "transcript.final",
                text: "帮我整理成一段话",
              }),
            });
          }, 30);
          return;
        }
        if (payload.type === "session.end") {
          this.close(1000, "client_end");
        }
      }

      close(code = 1000, reason = "") {
        if (this.readyState === MockWebSocket.CLOSED) {
          return;
        }
        this.readyState = MockWebSocket.CLOSED;
        setTimeout(() => {
          this.onclose?.({ code, reason });
        }, 0);
      }
    }

    Object.defineProperty(window, "WebSocket", {
      configurable: true,
      writable: true,
      value: MockWebSocket,
    });

    Object.defineProperty(globalThis, "WebSocket", {
      configurable: true,
      writable: true,
      value: MockWebSocket,
    });
  });
}

async function setPlaywrightProjects(
  page: Page,
  projects: Array<{ id: string; name: string; default_chat_mode?: string }>,
) {
  await page.addInitScript(
    ({ seededProjects }) => {
      (
        window as Window & {
          __PLAYWRIGHT_PROJECTS__?: Array<{
            id: string;
            name: string;
            default_chat_mode?: string;
          }>;
        }
      ).__PLAYWRIGHT_PROJECTS__ = seededProjects;
    },
    { seededProjects: projects },
  );
}

async function forceSelectChatProject(page: Page, projectId: string) {
  const select = page.locator(".inline-topbar-project-select");
  await expect(select).toBeVisible({ timeout: 10000 });
  await expect(select).toBeEnabled({ timeout: 10000 });
  await page.evaluate(
    ({ nextProjectId }) => {
      const select = document.querySelector<HTMLSelectElement>(
        ".inline-topbar-project-select",
      );
      if (!select) {
        return;
      }
      if (
        !Array.from(select.options).some(
          (option) => option.value === nextProjectId,
        )
      ) {
        const option = document.createElement("option");
        option.value = nextProjectId;
        option.textContent = nextProjectId;
        select.appendChild(option);
      }
    },
    { nextProjectId: projectId },
  );
  await select.selectOption(projectId);
  await expect(select).toHaveValue(projectId);
}

async function ensureChatConversationReady(page: Page, projectId: string) {
  const activeConversation = page.locator(".chat-sidebar-item.is-active");
  try {
    await expect(activeConversation).toBeVisible({ timeout: 8000 });
    return;
  } catch {
    await forceSelectChatProject(page, projectId);
    try {
      await expect(activeConversation).toBeVisible({ timeout: 8000 });
      return;
    } catch {
      // Fall through to the manual create path below.
    }
    const newConversationButton = page.locator(".chat-sidebar-new");
    await expect(newConversationButton).toBeEnabled({ timeout: 8000 });
    await newConversationButton.click();
    await expect(activeConversation).toBeVisible();
  }
}

async function stubAssistantMessageWithRetrievalTrace(
  page: Page,
  trace: Record<string, unknown>,
  content = "Mock assistant response",
) {
  await page.route(
    "**/api/v1/chat/conversations/*/messages",
    async (route, request) => {
      if (request.method() !== "POST") {
        await route.fallback();
        return;
      }

      const conversationId =
        request.url().match(/\/conversations\/([^/]+)\/messages$/)?.[1] ||
        "conv-001";
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "msg-trace-001",
          conversation_id: conversationId,
          role: "assistant",
          content,
          reasoning_content: null,
          metadata_json: {
            retrieval_trace: trace,
          },
          created_at: "2026-03-14T12:00:00.000Z",
        }),
      });
    },
  );
}

async function openChatToolsMenu(page: Page) {
  const trigger = page.getByRole("button", { name: "工具" });
  const menu = page.locator(".chat-tools-menu");

  await trigger.click();
  await expect(menu).toBeVisible();

  const triggerBox = await trigger.boundingBox();
  const menuBox = await menu.boundingBox();
  expect(triggerBox).not.toBeNull();
  expect(menuBox).not.toBeNull();
  if (!triggerBox || !menuBox) {
    return;
  }

  expect(menuBox.x).toBeGreaterThanOrEqual(Math.max(0, triggerBox.x - 32));
  expect(menuBox.x).toBeLessThanOrEqual(triggerBox.x + 32);
  expect(menuBox.y).toBeGreaterThanOrEqual(0);
  expect(menuBox.y + menuBox.height).toBeLessThanOrEqual(triggerBox.y + 16);
}

test.describe("Console Shell", () => {
  test.beforeEach(async ({ page }) => {
    await installWorkbenchApiMock(page, { authenticated: true });
  });

  test("applies console theme attributes", async ({ page }) => {
    await page.goto("/app");
    await expect(page.locator("[data-theme='console']").first()).toBeVisible();
    await expect(
      page.locator("header.site-header-v2.is-console"),
    ).toBeVisible();
  });

  test("IconBar visible on desktop", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/app");
    await expect(page.locator(".glass-sidebar--collapsed")).toBeVisible();
  });

  test("IconBar hidden on mobile", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto("/app");
    await expect(page.locator(".glass-sidebar--collapsed")).not.toBeVisible();
  });

  test("dashboard keeps the home chrome free of breadcrumb strips", async ({
    page,
  }) => {
    await page.goto("/app");
    await expect(
      page.locator("header.site-header-v2.is-console"),
    ).toBeVisible();
    await expect(page.locator(".inline-topbar-breadcrumb")).toHaveCount(0);
    await expect(page.locator("main [aria-label='Breadcrumb']")).toHaveCount(0);
  });

  test("dashboard shows all projects and their configured models", async ({
    page,
  }) => {
    await page.addInitScript(() => {
      (
        window as Window & {
          __PLAYWRIGHT_PROJECTS__?: Array<{
            id: string;
            name: string;
            default_chat_mode?:
              | "standard"
              | "omni_realtime"
              | "synthetic_realtime";
          }>;
        }
      ).__PLAYWRIGHT_PROJECTS__ = [
        {
          id: "proj-seed",
          name: "Seed Console Project",
          default_chat_mode: "standard",
        },
        {
          id: "proj-doctor",
          name: "医生",
          default_chat_mode: "omni_realtime",
        },
      ];
    });

    await page.route(
      "**/api/v1/pipeline?project_id=proj-seed",
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            items: [
              { model_type: "llm", model_id: "qwen3.5-plus" },
              { model_type: "tts", model_id: "qwen3-tts-flash" },
            ],
          }),
        });
      },
    );

    await page.route(
      "**/api/v1/pipeline?project_id=proj-doctor",
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            items: [
              { model_type: "llm", model_id: "qwen3.5-plus" },
              { model_type: "realtime", model_id: "qwen3-omni-flash-realtime" },
            ],
          }),
        });
      },
    );

    await page.route(
      "**/api/v1/chat/conversations?project_id=proj-seed",
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        });
      },
    );

    await page.route(
      "**/api/v1/chat/conversations?project_id=proj-doctor",
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        });
      },
    );

    await page.goto("/app");

    await expect(page.locator(".dashboard-project-card")).toHaveCount(2);
    await expect(
      page
        .locator(".dashboard-project-card")
        .filter({ hasText: "Seed Console Project" }),
    ).toContainText("Qwen3.5-Plus");
    await expect(
      page.locator(".dashboard-project-card").filter({ hasText: "医生" }),
    ).toContainText("Qwen3-Omni-Flash-Realtime");
  });

  test("dashboard cards open the assistant detail route", async ({ page }) => {
    await page.addInitScript(() => {
      (
        window as Window & {
          __PLAYWRIGHT_PROJECTS__?: Array<{
            id: string;
            name: string;
            default_chat_mode?:
              | "standard"
              | "omni_realtime"
              | "synthetic_realtime";
          }>;
        }
      ).__PLAYWRIGHT_PROJECTS__ = [
        {
          id: "proj-seed",
          name: "Seed Console Project",
          default_chat_mode: "standard",
        },
        {
          id: "proj-doctor",
          name: "医生",
          default_chat_mode: "omni_realtime",
        },
      ];
    });

    await page.route(
      "**/api/v1/pipeline?project_id=proj-seed",
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            items: [{ model_type: "llm", model_id: "qwen3.5-plus" }],
          }),
        });
      },
    );

    await page.route(
      "**/api/v1/pipeline?project_id=proj-doctor",
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            items: [
              { model_type: "realtime", model_id: "qwen3-omni-flash-realtime" },
            ],
          }),
        });
      },
    );

    await page.route(
      "**/api/v1/chat/conversations?project_id=proj-seed",
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        });
      },
    );

    await page.route(
      "**/api/v1/chat/conversations?project_id=proj-doctor",
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              id: "conv-doctor",
              title: "医生建议",
              updated_at: "2026-03-20T12:00:00.000Z",
            },
          ]),
        });
      },
    );

    await page.goto("/app");
    await page.getByTestId("dashboard-project-card-proj-doctor").click();
    await expect(page).toHaveURL(/\/app\/assistants\/proj-doctor$/);
  });

  test("StatusBar visible on desktop", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/app");
    await expect(page.locator(".statusbar")).toBeVisible();
  });

  test("StatusBar hidden on mobile", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto("/app");
    await expect(page.locator(".statusbar")).not.toBeVisible();
  });

  test("Cmd+K opens command palette", async ({ page }) => {
    const accessibilityWarnings: string[] = [];
    page.on("console", (message) => {
      const text = message.text();
      if (text.includes("DialogContent requires a DialogTitle")) {
        accessibilityWarnings.push(text);
      }
    });

    await page.goto("/app");
    await page.keyboard.press("Meta+k");
    await expect(page.locator("[role='dialog']")).toBeVisible();
    await expect(page.getByPlaceholder("输入命令或搜索…")).toBeVisible();
    expect(accessibilityWarnings).toEqual([]);
  });

  test("navigation works via IconBar", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/app");
    await page.getByRole("link", { name: "对话" }).click();
    await expect(page).toHaveURL(/\/app\/chat$/);
  });

  test("english console shell also renders correctly", async ({ page }) => {
    await page.goto("/en/app");
    await expect(
      page.locator("header.site-header-v2.is-console"),
    ).toContainText("Mingrun");
    await expect(page.getByRole("heading", { name: "My AI" })).toBeVisible();
  });

  test("discover routes fall back to the console home when disabled", async ({
    page,
  }) => {
    await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto("/app/discover");
    await expect(page.getByRole("heading", { name: "我的 AI" })).toBeVisible();

    await page.goto("/app/discover/models/qwen3-vl-plus");
    await expect(page.getByRole("heading", { name: "我的 AI" })).toBeVisible();

    await page.goto("/app/discover/packs/demo-pack");
    await expect(page).toHaveURL(/\/app$/);
  });

  test("english discover routes also fall back to the console home", async ({
    page,
  }) => {
    await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto("/en/app/discover");
    await expect(page.getByRole("heading", { name: "My AI" })).toBeVisible();

    await page.goto("/en/app/discover/models/qwen3.5-plus");
    await expect(page.getByRole("heading", { name: "My AI" })).toBeVisible();

    await page.goto("/en/app/discover/packs/demo-pack");
    await expect(page).toHaveURL(/\/en\/app$/);
  });

  test("discover navigation entry is hidden from console navigation", async ({
    page,
  }) => {
    await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto("/app");
    await expect(page.locator('a[href="/app/discover"]')).toHaveCount(0);
  });

  test("discover falls back without requesting disabled catalog surfaces", async ({
    page,
  }) => {
    let catalogRequestCount = 0;

    await page.route(
      "**/api/v1/models/catalog?view=discover",
      async (route) => {
        catalogRequestCount += 1;
        await route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ error: { message: "broken" } }),
        });
      },
    );

    await page.goto("/app/discover");
    await expect(page.getByRole("heading", { name: "我的 AI" })).toBeVisible();
    expect(catalogRequestCount).toBe(0);
  });

  test("assistant detail route renders current action surface without 5xx responses", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });
    const failingResponses: string[] = [];

    page.on("response", (response) => {
      const url = response.url();
      if (
        url.includes(`/app/assistants/${handle.seedProjectId}`) &&
        response.status() >= 500
      ) {
        failingResponses.push(`${response.status()} ${url}`);
      }
    });

    await page.goto(`/app/assistants/${handle.seedProjectId}`);
    await expect(page.getByRole("link", { name: "开始聊天" })).toBeVisible();
    await expect(
      page
        .locator(".assistant-profile-actions")
        .getByRole("button", { name: "设置" }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "管理" })).toBeVisible();
    expect(failingResponses).toEqual([]);
  });

  test("assistant dialogs stay inside the console theme container", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/assistants/${handle.seedProjectId}`);
    await page
      .locator(".assistant-profile-actions")
      .getByRole("button", { name: "设置" })
      .click();

    const dialog = page
      .locator('[data-theme="console"] [role="dialog"]')
      .first();
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("给它一个名字和形象");
  });

  test("assistant detail collapses covered vision model slots into the chat model", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/assistants/${handle.seedProjectId}`);

    const visionRow = page
      .locator(".profile-model-row")
      .filter({ hasText: "视觉理解" })
      .first();
    await expect(visionRow).toContainText("Qwen 3.5 Plus");
    await expect(visionRow).toContainText("跟随对话模型");
    await expect(visionRow).toContainText("图像输入会直接交给 Qwen 3.5 Plus");
    await expect(visionRow.getByRole("button", { name: "更换" })).toHaveCount(
      0,
    );
  });

  test("assistant detail shows a dedicated realtime model row", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/assistants/${handle.seedProjectId}`);

    const realtimeRow = page
      .locator(".profile-model-row")
      .filter({ hasText: "实时对话" })
      .first();
    await expect(realtimeRow).toContainText("Qwen3-Omni-Flash-Realtime");
    await expect(realtimeRow).toContainText(
      "实时双工语音当前使用 Qwen3-Omni-Flash-Realtime",
    );
    await expect(realtimeRow.getByRole("button", { name: "更换" })).toHaveCount(
      1,
    );
  });

  test("assistant detail opens the model picker from grouped model rows", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/assistants/${handle.seedProjectId}`);
    await page.getByTestId("assistant-model-change-realtime").click();
    await expect(page.locator(".model-picker-title")).toContainText("实时对话");
  });

  test("assistant detail opens a realtime-only model picker", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/assistants/${handle.seedProjectId}`);
    await page
      .locator(".profile-model-row")
      .filter({ hasText: "实时对话" })
      .first()
      .getByRole("button", { name: "更换" })
      .click();

    const modal = page.locator(".model-picker-card");
    await expect(modal).toBeVisible();
    await expect(modal).toContainText("实时对话");
    await expect(modal).toContainText("Qwen3-Omni-Flash-Realtime");
    await expect(modal).not.toContainText("Qwen 3.5 Plus");
  });

  test("assistant detail round-trips through the marketplace detail picker flow", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/assistants/${handle.seedProjectId}`);
    await page.getByTestId("assistant-model-change-llm").click();
    await page.getByRole("link", { name: "前往模型广场" }).click();

    await expect(page).toHaveURL(/\/app\/discover\?picker=1&category=llm/);
    await page
      .locator(".dhub-model-card")
      .filter({ hasText: "Qwen Max" })
      .first()
      .click();
    await expect(page.getByRole("heading", { name: "Qwen Max" })).toBeVisible();
    await expect(page.getByRole("link", { name: "返回上一页" })).toHaveCount(1);
    await expect(
      page.getByRole("button", { name: "使用此模型" }),
    ).toBeEnabled();
    await page.getByRole("button", { name: "使用此模型" }).click();

    await expect(page).toHaveURL(
      new RegExp(`/app/assistants/${handle.seedProjectId}$`),
    );
    const llmRow = page
      .locator(".profile-model-row")
      .filter({ hasText: "对话模型" })
      .first();
    await expect(llmRow).toContainText("Qwen Max");
  });

  test("assistant detail shows dedicated synthetic realtime model rows", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/assistants/${handle.seedProjectId}`);
    await page.getByRole("button", { name: "模型" }).click();

    const syntheticSection = page
      .locator(".profile-mode-section-header")
      .filter({ hasText: "合成式实时" })
      .first()
      .locator("..");
    await expect(syntheticSection).toContainText("合成实时对话模型");
    await expect(syntheticSection).toContainText("实时语音识别");
    await expect(syntheticSection).toContainText("Qwen3-ASR-Flash-Realtime");
    await expect(syntheticSection).toContainText("实时语音合成");
    await expect(syntheticSection).toContainText("Qwen3-TTS-Flash-Realtime");
  });

  test("assistant detail saves the default chat mode", async ({ page }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });
    const patchedBodies: Array<{ default_chat_mode?: string }> = [];

    await page.route(
      `**/api/v1/projects/${handle.seedProjectId}`,
      async (route) => {
        if (route.request().method().toUpperCase() !== "PATCH") {
          await route.fallback();
          return;
        }

        patchedBodies.push(
          route.request().postDataJSON() as { default_chat_mode?: string },
        );
        await route.fallback();
      },
    );

    await page.goto(`/app/assistants/${handle.seedProjectId}`);
    await page.getByRole("button", { name: "模型" }).click();
    await page
      .locator(".profile-mode-card")
      .filter({ hasText: "合成式实时" })
      .first()
      .click();

    await expect
      .poll(() => patchedBodies.at(-1)?.default_chat_mode)
      .toBe("synthetic_realtime");
    await expect(
      page
        .locator(".profile-mode-card.is-active")
        .filter({ hasText: "合成式实时" })
        .first(),
    ).toBeVisible();
  });

  test("chat timeout errors stay localized", async ({ page }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.route(
      "**/api/v1/chat/conversations/*/messages",
      async (route) => {
        await route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({
            error: {
              code: "inference_timeout",
              message: "Inference timeout",
            },
          }),
        });
      },
    );

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await ensureChatConversationReady(page, handle.seedProjectId);
    await expect(
      page.getByRole("textbox", { name: "输入消息…" }).first(),
    ).toBeEnabled();

    await page.getByRole("textbox", { name: "输入消息…" }).fill("测试超时");
    await page.getByRole("button", { name: "发送" }).click();

    await expect(
      page.locator(".chat-message.is-assistant").last(),
    ).toContainText("AI 回复超时，请稍后重试。");
  });

  test("chat message history loads through the app origin instead of cross-origin api calls", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });
    let messageRequestUrl = "";

    await page.route(
      `**/api/v1/chat/conversations?project_id=${handle.seedProjectId}`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              id: "conv-proxy",
              project_id: handle.seedProjectId,
              title: "代理会话",
              updated_at: "2026-03-18T08:00:00.000Z",
            },
          ]),
        });
      },
    );

    await page.route(
      "**/api/v1/chat/conversations/conv-proxy/messages",
      async (route, request) => {
        messageRequestUrl = request.url();
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              id: "msg-proxy-1",
              role: "user",
              content: "通过同源代理读取历史消息",
              created_at: "2026-03-18T08:00:00.000Z",
            },
          ]),
        });
      },
    );

    await page.goto(
      `/app/chat?project_id=${handle.seedProjectId}&conv=conv-proxy`,
    );
    await expect(page.locator(".chat-message.is-user").first()).toContainText(
      "通过同源代理读取历史消息",
    );

    expect(new URL(messageRequestUrl).origin).toBe(new URL(page.url()).origin);
  });

  test("chat mic button dictates into the input instead of sending immediately", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });
    await stubRealtimeDictationApis(page);

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await ensureChatConversationReady(page, handle.seedProjectId);
    await ensureChatConversationReady(page, handle.seedProjectId);
    await page.locator(".chat-mic-btn").click();
    await expect(page.locator(".chat-voice-indicator")).toContainText(
      "听写中…再次点击完成",
    );
    await expect
      .poll(async () =>
        page.evaluate(
          () =>
            (window as Window & { __lastDictationBufferSize?: number })
              .__lastDictationBufferSize ?? 0,
        ),
      )
      .toBe(1024);
    await expect(page.getByRole("textbox", { name: "输入消息…" })).toHaveValue(
      "帮我",
    );

    await page.locator(".chat-mic-btn").click();

    await expect(page.getByRole("textbox", { name: "输入消息…" })).toHaveValue(
      "帮我整理成一段话",
    );
    await expect(page.locator(".chat-message.is-user")).toHaveCount(0);
  });

  test("assistant messages can be read aloud on demand", async ({ page }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });
    const speechBodies: Array<{ content?: string }> = [];

    await stubBrowserVoiceApis(page);
    await page.route("**/api/v1/chat/conversations/*/speech", async (route) => {
      speechBodies.push(route.request().postDataJSON() as { content?: string });
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          audio_response: "AQID",
        }),
      });
    });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await ensureChatConversationReady(page, handle.seedProjectId);
    await page.getByRole("textbox", { name: "输入消息…" }).fill("帮我回答");
    await page.getByRole("button", { name: "发送" }).click();

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    await expect(assistantMessage).toContainText("Mock assistant response");
    await assistantMessage.getByRole("button", { name: "朗读" }).click();

    await expect.poll(() => speechBodies.length).toBe(1);
    expect(speechBodies).toEqual([{ content: "Mock assistant response" }]);
  });

  test("short user bubbles stay horizontal instead of collapsing into a narrow column", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await ensureChatConversationReady(page, handle.seedProjectId);
    await ensureChatConversationReady(page, handle.seedProjectId);
    await page
      .getByRole("textbox", { name: "输入消息…" })
      .fill("介绍一下你自己");
    await page.getByRole("button", { name: "发送" }).click();

    const userBubble = page
      .locator(".chat-message.is-user .chat-bubble")
      .last();
    await expect(userBubble).toContainText("介绍一下你自己");

    const box = await userBubble.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeGreaterThan(120);
    expect(box!.width).toBeGreaterThan(box!.height);
  });

  test("chat history scroll stays inside the conversation pane instead of extending the page", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.route(
      `**/api/v1/chat/conversations?project_id=${handle.seedProjectId}`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              id: "conv-scroll-pane",
              project_id: handle.seedProjectId,
              title: "滚动测试",
              updated_at: "2026-03-18T08:00:00.000Z",
            },
          ]),
        });
      },
    );

    await page.route(
      "**/api/v1/chat/conversations/conv-scroll-pane/messages",
      async (route) => {
        const messages = Array.from({ length: 18 }, (_, index) => ({
          id: `msg-scroll-${index + 1}`,
          role: index % 2 === 0 ? "assistant" : "user",
          content: "这是一条用于滚动测试的长消息。".repeat(
            index % 2 === 0 ? 10 : 6,
          ),
          created_at: `2026-03-18T08:${String(index).padStart(2, "0")}:00.000Z`,
        }));

        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(messages),
        });
      },
    );

    await page.goto(
      `/app/chat?project_id=${handle.seedProjectId}&conv=conv-scroll-pane`,
    );
    await expect(page.locator(".chat-message").last()).toBeVisible();

    const scrollability = await page.evaluate(() => {
      const shell = document.querySelector<HTMLElement>(".console-shell-main");
      const messages = document.querySelector<HTMLElement>(
        ".chat-main .chat-messages",
      );
      if (!shell || !messages) {
        return null;
      }
      return {
        shellScrollable: shell.scrollHeight > shell.clientHeight + 2,
        messagesScrollable: messages.scrollHeight > messages.clientHeight + 2,
      };
    });

    expect(scrollability).toEqual({
      shellScrollable: false,
      messagesScrollable: true,
    });

    await page.locator(".chat-main .chat-messages").hover();
    await page.mouse.wheel(0, 900);

    const scrollPositions = await page.evaluate(() => {
      const shell = document.querySelector<HTMLElement>(".console-shell-main");
      const messages = document.querySelector<HTMLElement>(
        ".chat-main .chat-messages",
      );
      return {
        shellTop: shell?.scrollTop ?? -1,
        messagesTop: messages?.scrollTop ?? -1,
      };
    });

    expect(scrollPositions.shellTop).toBe(0);
    expect(scrollPositions.messagesTop).toBeGreaterThan(0);
  });

  test("streamed replies still render when only the final message_done event carries content", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.route("**/api/v1/chat/conversations/*/stream", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          "event: message_start",
          'data: {"role":"assistant"}',
          "",
          "event: message_done",
          'data: {"id":"msg-stream-final","content":"来自最终事件的完整回复","reasoning_content":"最终思考轨迹"}',
          "",
        ].join("\n"),
      });
    });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await ensureChatConversationReady(page, handle.seedProjectId);
    await page
      .getByRole("textbox", { name: "输入消息…" })
      .fill("测试流式最终事件");
    await page.getByRole("button", { name: "发送" }).click();

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    await expect(assistantMessage.locator(".chat-bubble")).toContainText(
      "来自最终事件的完整回复",
    );
    await expect(assistantMessage.locator(".chat-thinking-inline")).toContainText(
      "思考步骤",
    );
    await assistantMessage.locator(".chat-thinking-inline-toggle").click();
    await expect(assistantMessage.locator(".chat-thinking-inline-body")).toContainText(
      "最终思考轨迹",
    );
  });

  test("multiple stream events delivered in one response chunk still appear progressively", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });
    await page.addInitScript(() => {
      Object.defineProperty(window, "requestAnimationFrame", {
        configurable: true,
        writable: true,
        value: (callback: FrameRequestCallback) =>
          window.setTimeout(() => callback(performance.now()), 60),
      });
    });

    await page.route("**/api/v1/chat/conversations/*/stream", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          "event: message_start",
          'data: {"role":"assistant"}',
          "",
          "event: reasoning",
          'data: {"content":"先想第一步。"}',
          "",
          "event: reasoning",
          'data: {"content":"再想第二步。"}',
          "",
          "event: token",
          'data: {"content":"先给第一句。"}',
          "",
          "event: token",
          'data: {"content":"再给第二句。"}',
          "",
          "event: message_done",
          'data: {"id":"msg-stream-progressive","content":"先给第一句。再给第二句。","reasoning_content":"先想第一步。再想第二步。"}',
          "",
        ].join("\n"),
      });
    });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await ensureChatConversationReady(page, handle.seedProjectId);
    await openChatToolsMenu(page);
    await page
      .locator(".chat-tools-menu-item", { hasText: "深入分析" })
      .click();
    await page.getByRole("textbox", { name: "输入消息…" }).fill("测试逐步流式");
    await page.getByRole("button", { name: "发送" }).click();

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    const thinkingBody = assistantMessage.locator(".chat-thinking-inline-body");

    await expect(thinkingBody).toContainText("先想第一步。");
    await expect(thinkingBody).not.toContainText("再想第二步。");
    await expect(assistantMessage.locator(".chat-bubble")).toContainText(
      "先给第一句。",
    );
    await expect(assistantMessage.locator(".chat-bubble")).not.toContainText(
      "再给第二句。",
    );

    await expect(thinkingBody).toContainText("再想第二步。");
    await expect(assistantMessage.locator(".chat-bubble")).toContainText(
      "再给第二句。",
    );
  });

  test("streaming replies keep partial markdown as plain text until the final message lands", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });
    await page.addInitScript(() => {
      Object.defineProperty(window, "requestAnimationFrame", {
        configurable: true,
        writable: true,
        value: (callback: FrameRequestCallback) =>
          window.setTimeout(() => callback(performance.now()), 60),
      });
    });

    await page.route("**/api/v1/chat/conversations/*/stream", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          "event: message_start",
          'data: {"role":"assistant"}',
          "",
          "event: token",
          'data: {"content":"### 1. 出发点：德布罗意关系","snapshot":"### 1. 出发点：德布罗意关系"}',
          "",
          "event: token",
          'data: {"content":"\\n\\n这里是补充说明。","snapshot":"### 1. 出发点：德布罗意关系\\n\\n这里是补充说明。"}',
          "",
          "event: message_done",
          'data: {"id":"msg-stream-markdown-final","content":"### 1. 出发点：德布罗意关系\\n\\n这里是补充说明。","reasoning_content":null}',
          "",
        ].join("\n"),
      });
    });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await ensureChatConversationReady(page, handle.seedProjectId);
    await page.getByRole("textbox", { name: "输入消息…" }).fill("测试流式 markdown");
    await page.getByRole("button", { name: "发送" }).click();

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    await expect(assistantMessage.locator(".chat-bubble")).toContainText(
      "### 1. 出发点：德布罗意关系",
    );
    await expect(
      assistantMessage.getByRole("heading", { name: "1. 出发点：德布罗意关系" }),
    ).toHaveCount(0);

    await expect(
      assistantMessage.getByRole("heading", { name: "1. 出发点：德布罗意关系" }),
    ).toBeVisible();
    await expect(assistantMessage.locator(".chat-bubble")).not.toContainText("###");
    await expect(assistantMessage.locator(".chat-bubble")).toContainText(
      "这里是补充说明。",
    );
  });

  test("streamed replies hydrate late sources and memory metadata without a manual refresh", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, {
      authenticated: true,
      seedConversations: [
        {
          id: "conv-late-metadata",
          title: "延迟元数据测试",
        },
      ],
    });
    let messageFetchCount = 0;

    await page.route(
      "**/api/v1/chat/conversations/conv-late-metadata/messages",
      async (route, request) => {
        if (request.method() !== "GET") {
          await route.fallback();
          return;
        }

        messageFetchCount += 1;
        const body =
          messageFetchCount === 1
            ? []
            : [
                {
                  id: "msg-user-late-metadata",
                  conversation_id: "conv-late-metadata",
                  role: "user",
                  content: "帮我联网查一下并记住结果",
                  created_at: "2026-03-14T12:00:00.000Z",
                },
                {
                  id: "msg-assistant-late-metadata",
                  conversation_id: "conv-late-metadata",
                  role: "assistant",
                  content: "先给你正文，来源和记忆稍后补齐。",
                  reasoning_content: null,
                  metadata_json: {
                    sources: [
                      {
                        index: 1,
                        title: "Aliyun Docs",
                        url: "https://help.aliyun.com/zh/model-studio/web-search",
                        domain: "help.aliyun.com",
                        site_name: "Aliyun Docs",
                      },
                    ],
                    extracted_facts: [
                      {
                        fact: "用户希望后续默认附上网页来源",
                        category: "偏好",
                        importance: 0.87,
                        status: "permanent",
                        triage_action: "create",
                        triage_reason: "这是稳定的输出偏好。",
                      },
                    ],
                  },
                  created_at: "2026-03-14T12:00:01.000Z",
                },
              ];

        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(body),
        });
      },
    );

    await page.route("**/api/v1/chat/conversations/*/stream", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          "event: message_start",
          'data: {"role":"assistant"}',
          "",
          "event: message_done",
          'data: {"id":"msg-assistant-late-metadata","content":"先给你正文，来源和记忆稍后补齐。"}',
          "",
        ].join("\n"),
      });
    });

    await page.goto(
      `/app/chat?project_id=${handle.seedProjectId}&conv=conv-late-metadata`,
    );

    await expect(page.locator(".chat-sidebar-item.is-active")).toBeVisible();
    await page
      .getByRole("textbox", { name: "输入消息…" })
      .fill("帮我联网查一下并记住结果");
    await page.getByRole("button", { name: "发送" }).click();

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    await expect(assistantMessage.locator(".chat-bubble")).toContainText(
      "先给你正文，来源和记忆稍后补齐。",
    );
    await expect(
      assistantMessage.locator(".chat-source-summary-trigger"),
    ).toContainText("来源", { timeout: 5000 });
    await expect(assistantMessage.locator(".chat-memory-summary-card")).toContainText(
      "用户希望后续默认附上网页来源",
      { timeout: 5000 },
    );
    expect(messageFetchCount).toBeGreaterThanOrEqual(2);
  });

  test("streamed replies with pending extraction hydrate memory cards as soon as metadata events arrive", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, {
      authenticated: true,
      seedConversations: [
        {
          id: "conv-stream-memory-events",
          title: "流式记忆事件测试",
        },
      ],
    });
    let messageFetchCount = 0;

    await page.addInitScript(() => {
      class MockEventSource {
        url: string;
        withCredentials: boolean;
        onerror: ((event: Event) => void) | null = null;
        private listeners = new Map<
          string,
          Array<(event: MessageEvent<string>) => void>
        >();

        constructor(url: string | URL, init?: EventSourceInit) {
          this.url = String(url);
          this.withCredentials = Boolean(init?.withCredentials);

          if (
            this.url.includes(
              "/api/v1/chat/conversations/conv-stream-memory-events/events",
            )
          ) {
            setTimeout(() => {
              const payload = {
                id: "msg-stream-memory-001",
                metadata_json: {
                  memory_extraction_status: "completed",
                  memories_extracted: "新增永久记忆 1 条",
                  extracted_facts: [
                    {
                      fact: "用户现在是大一学生。",
                      category: "教育.学业阶段",
                      importance: 0.95,
                      status: "permanent",
                      triage_action: "create",
                      triage_reason: "这是稳定的教育阶段信息。",
                    },
                  ],
                },
              };
              const callbacks =
                this.listeners.get("assistant_message_metadata") || [];
              for (const callback of callbacks) {
                callback(
                  new MessageEvent("assistant_message_metadata", {
                    data: JSON.stringify(payload),
                  }),
                );
              }
            }, 250);
          }
        }

        addEventListener(
          type: string,
          listener: EventListenerOrEventListenerObject,
        ) {
          const callback =
            typeof listener === "function"
              ? (listener as (event: MessageEvent<string>) => void)
              : (event: MessageEvent<string>) => listener.handleEvent(event);
          const existing = this.listeners.get(type) || [];
          existing.push(callback);
          this.listeners.set(type, existing);
        }

        removeEventListener(
          type: string,
          listener: EventListenerOrEventListenerObject,
        ) {
          const existing = this.listeners.get(type) || [];
          const callback =
            typeof listener === "function"
              ? (listener as (event: MessageEvent<string>) => void)
              : (event: MessageEvent<string>) => listener.handleEvent(event);
          this.listeners.set(
            type,
            existing.filter((item) => item !== callback),
          );
        }

        close() {
          return undefined;
        }
      }

      Object.defineProperty(window, "EventSource", {
        configurable: true,
        writable: true,
        value: MockEventSource,
      });

      Object.defineProperty(globalThis, "EventSource", {
        configurable: true,
        writable: true,
        value: MockEventSource,
      });
    });

    await page.route(
      "**/api/v1/chat/conversations/conv-stream-memory-events/messages",
      async (route, request) => {
        if (request.method() !== "GET") {
          await route.fallback();
          return;
        }

        messageFetchCount += 1;
        const body =
          messageFetchCount === 1
            ? []
            : [
                {
                  id: "msg-user-stream-memory-001",
                  conversation_id: "conv-stream-memory-events",
                  role: "user",
                  content: "记一下我现在是大一学生",
                  created_at: "2026-03-14T12:00:00.000Z",
                },
                {
                  id: "msg-stream-memory-001",
                  conversation_id: "conv-stream-memory-events",
                  role: "assistant",
                  content: "先回答你，记忆很快补上。",
                  reasoning_content: null,
                  metadata_json: {
                    memory_extraction_status: "completed",
                    memories_extracted: "新增永久记忆 1 条",
                    extracted_facts: [
                      {
                        fact: "用户现在是大一学生。",
                        category: "教育.学业阶段",
                        importance: 0.95,
                        status: "permanent",
                        triage_action: "create",
                        triage_reason: "这是稳定的教育阶段信息。",
                      },
                    ],
                  },
                  created_at: "2026-03-14T12:00:01.000Z",
                },
              ];

        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(body),
        });
      },
    );

    await page.route("**/api/v1/chat/conversations/*/stream", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          "event: message_start",
          'data: {"role":"assistant"}',
          "",
          "event: message_done",
          'data: {"id":"msg-stream-memory-001","content":"先回答你，记忆很快补上。","memory_extraction_status":"pending"}',
          "",
        ].join("\n"),
      });
    });

    await page.goto(
      `/app/chat?project_id=${handle.seedProjectId}&conv=conv-stream-memory-events`,
    );

    await expect(page.locator(".chat-sidebar-item.is-active")).toBeVisible();
    await page
      .getByRole("textbox", { name: "输入消息…" })
      .fill("记一下我现在是大一学生");
    await page.getByRole("button", { name: "发送" }).click();

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    await expect(assistantMessage.locator(".chat-bubble")).toContainText(
      "先回答你，记忆很快补上。",
    );
    await expect(assistantMessage.locator(".chat-memory-summary-card")).toContainText(
      "用户现在是大一学生。",
      { timeout: 5000 },
    );
    expect(messageFetchCount).toBeGreaterThanOrEqual(1);
  });

  test("deep think shows reasoning content and read aloud still uses the final answer", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });
    const messageBodies: Array<{
      content?: string;
      enable_thinking?: boolean;
    }> = [];
    const speechBodies: Array<{ content?: string }> = [];

    await stubBrowserVoiceApis(page);
    await page.route(
      "**/api/v1/chat/conversations/*/messages",
      async (route, request) => {
        if (request.method() === "POST") {
          messageBodies.push(
            request.postDataJSON() as {
              content?: string;
              enable_thinking?: boolean;
            },
          );
        }
        await route.fallback();
      },
    );
    await page.route("**/api/v1/chat/conversations/*/speech", async (route) => {
      speechBodies.push(route.request().postDataJSON() as { content?: string });
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          audio_response: "AQID",
        }),
      });
    });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await ensureChatConversationReady(page, handle.seedProjectId);
    await openChatToolsMenu(page);
    await page
      .locator(".chat-tools-menu-item", { hasText: "深入分析" })
      .click();
    await page.getByRole("textbox", { name: "输入消息…" }).fill("请拆解一下");
    await page.getByRole("button", { name: "发送" }).click();

    await expect.poll(() => messageBodies.length).toBe(1);
    expect(messageBodies[0]).toEqual({
      content: "请拆解一下",
      enable_thinking: true,
    });

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    await expect(assistantMessage.locator(".chat-thinking-inline")).toContainText(
      "思考步骤",
    );
    await expect(assistantMessage.locator(".chat-bubble")).toContainText(
      "Mock assistant response",
    );
    await assistantMessage.locator(".chat-thinking-inline-toggle").click();
    await expect(assistantMessage.locator(".chat-thinking-inline-body")).toContainText(
      "Mock reasoning trace",
    );

    await assistantMessage.getByRole("button", { name: "朗读" }).click();
    await expect.poll(() => speechBodies.length).toBe(1);
    expect(speechBodies[0]).toEqual({ content: "Mock assistant response" });
  });

  test("assistant messages with sources render a compact source entry and inspector cards", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.route(
      "**/api/v1/chat/conversations/*/messages",
      async (route, request) => {
        if (request.method() !== "POST") {
          await route.fallback();
          return;
        }

        const conversationId =
          request.url().match(/\/conversations\/([^/]+)\/messages$/)?.[1] ||
          "conv-001";
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "msg-source-001",
            conversation_id: conversationId,
            role: "assistant",
            content:
              "**结论**：根据公开资料，公式 $E=mc^2$ 可以正常显示。[ref_1]",
            reasoning_content: null,
            metadata_json: {
              sources: [
                {
                  index: 1,
                  title: "Aliyun Web Search",
                  url: "https://help.aliyun.com/zh/model-studio/web-search",
                  domain: "help.aliyun.com",
                  site_name: "Aliyun Docs",
                },
              ],
            },
            created_at: "2026-03-14T12:00:00.000Z",
          }),
        });
      },
    );

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await ensureChatConversationReady(page, handle.seedProjectId);
    await page.getByRole("textbox", { name: "输入消息…" }).fill("帮我查一下");
    await page.getByRole("button", { name: "发送" }).click();

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    await expect(assistantMessage.locator(".chat-bubble strong")).toContainText(
      "结论",
    );
    await expect(assistantMessage.locator(".chat-bubble .katex")).toBeVisible();
    await expect(
      assistantMessage.locator(".chat-citation-anchor"),
    ).toContainText("[1]");
    await assistantMessage.locator(".chat-citation-anchor").hover();
    await expect(
      assistantMessage.locator(".chat-citation-preview"),
    ).toContainText("Aliyun Web Search");
    await expect(
      assistantMessage.locator(".chat-citation-preview"),
    ).toContainText("根据公开资料，公式 $E=mc^2$ 可以正常显示。");
    const sourceSummary = assistantMessage.locator(".chat-source-summary-trigger");
    await expect(sourceSummary).toContainText("来源");
    await expect(sourceSummary).toContainText("1");
    await expect(
      sourceSummary.locator(".chat-source-favicon"),
    ).toBeVisible();
    await sourceSummary.click();
    const inspectorSourceCard = page
      .locator(".chat-inspector-panel .chat-inspector-source-card")
      .first();
    await expect(inspectorSourceCard).toContainText("Aliyun Web Search");
    await expect(inspectorSourceCard).toContainText("Aliyun Docs");
    await expect(inspectorSourceCard).toHaveAttribute(
      "href",
      "https://help.aliyun.com/zh/model-studio/web-search",
    );
  });

  test("assistant messages normalize malformed adjacent math blocks", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.route(
      "**/api/v1/chat/conversations/*/messages",
      async (route, request) => {
        if (request.method() !== "POST") {
          await route.fallback();
          return;
        }

        const conversationId =
          request.url().match(/\/conversations\/([^/]+)\/messages$/)?.[1] ||
          "conv-001";
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "msg-math-fix-001",
            conversation_id: conversationId,
            role: "assistant",
            content:
              "- 对时间求导:$$\\frac{\\partial \\psi}{\\partial t}=-i\\omega\\psi$$$\\Rightarrowi\\hbar\\frac{\\partial \\psi}{\\partial t}=E\\psi$$",
            reasoning_content: null,
            metadata_json: {},
            created_at: "2026-03-31T09:30:00.000Z",
          }),
        });
      },
    );

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await ensureChatConversationReady(page, handle.seedProjectId);
    await page.getByRole("textbox", { name: "输入消息…" }).fill("解释一下");
    await page.getByRole("button", { name: "发送" }).click();

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    await expect(assistantMessage.locator(".chat-bubble")).toContainText(
      "对时间求导",
    );
    await expect
      .poll(() => assistantMessage.locator(".chat-bubble .katex").count())
      .toBe(2);
    await expect(
      assistantMessage.locator(".chat-bubble .katex-error"),
    ).toHaveCount(0);
    await expect(assistantMessage.locator(".chat-bubble")).not.toContainText(
      "\\Rightarrowi",
    );
    await expect(assistantMessage.locator(".chat-bubble")).not.toContainText(
      "\\Rightarrow",
    );
  });

  test("assistant messages merge dangling colon lines before rendering", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.route(
      "**/api/v1/chat/conversations/*/messages",
      async (route, request) => {
        if (request.method() !== "POST") {
          await route.fallback();
          return;
        }

        const conversationId =
          request.url().match(/\/conversations\/([^/]+)\/messages$/)?.[1] ||
          "conv-001";
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "msg-colon-fix-001",
            conversation_id: conversationId,
            role: "assistant",
            content:
              "Campofrío\n\n: 西班牙最大的肉制品公司之一，产品线极广，从入门到高端都有。\n\nEl Pozo\n\n： 另一家大型食品集团，常见于各大超市。\n\n给“董铭锡”的特别操作建议\n\n：\n\n选择部位\n\n： 如果购买整腿或切片，尽量选取脂肪较少的部位。",
            reasoning_content: null,
            metadata_json: {},
            created_at: "2026-03-31T13:35:00.000Z",
          }),
        });
      },
    );

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await ensureChatConversationReady(page, handle.seedProjectId);
    await page.getByRole("textbox", { name: "输入消息…" }).fill("继续");
    await page.getByRole("button", { name: "发送" }).click();

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    await expect
      .poll(async () =>
        assistantMessage
          .locator(".chat-bubble")
          .evaluate((node) => node.textContent || ""),
      )
      .toContain("Campofrío: 西班牙最大的肉制品公司之一");
    await expect
      .poll(async () =>
        assistantMessage
          .locator(".chat-bubble")
          .evaluate((node) => node.textContent || ""),
      )
      .toContain(
        "Campofrío: 西班牙最大的肉制品公司之一，产品线极广，从入门到高端都有。",
      );
    await expect
      .poll(async () =>
        assistantMessage
          .locator(".chat-bubble")
          .evaluate((node) => node.textContent || ""),
      )
      .toContain("El Pozo： 另一家大型食品集团，常见于各大超市。");
    await expect
      .poll(async () =>
        assistantMessage
          .locator(".chat-bubble")
          .evaluate((node) => node.textContent || ""),
      )
      .toContain("给“董铭锡”的特别操作建议：");
    await expect
      .poll(async () =>
        assistantMessage
          .locator(".chat-bubble")
          .evaluate((node) => node.textContent || ""),
      )
      .toContain("选择部位： 如果购买整腿或切片，尽量选取脂肪较少的部位。");
    const bubbleText = await assistantMessage
      .locator(".chat-bubble")
      .evaluate((node) => node.textContent || "");
    expect(bubbleText).not.toContain("\n:");
    expect(bubbleText).not.toContain("\n：");
  });

  test("assistant messages render normalized headings and math commands", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.route(
      "**/api/v1/chat/conversations/*/messages",
      async (route, request) => {
        if (request.method() !== "POST") {
          await route.fallback();
          return;
        }

        const conversationId =
          request.url().match(/\/conversations\/([^/]+)\/messages$/)?.[1] ||
          "conv-001";
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "msg-heading-math-fix-001",
            conversation_id: conversationId,
            role: "assistant",
            content:
              "薛定谔方程的启发式推导\n### 1. 出发点：德布罗意关系\n$$\\frac{\\partial^2 \\psi}{\\partial x^2}=-k^2\\psi$$\n### 5. 加入势能项",
            reasoning_content: null,
            metadata_json: {},
            created_at: "2026-03-31T15:52:00.000Z",
          }),
        });
      },
    );

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await ensureChatConversationReady(page, handle.seedProjectId);
    await page.getByRole("textbox", { name: "输入消息…" }).fill("继续");
    await page.getByRole("button", { name: "发送" }).click();

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    await expect(
      assistantMessage.getByRole("heading", {
        name: "1. 出发点：德布罗意关系",
      }),
    ).toBeVisible();
    await expect(
      assistantMessage.getByRole("heading", { name: "5. 加入势能项" }),
    ).toBeVisible();
    await expect(assistantMessage.locator(".chat-bubble .katex")).toBeVisible();
    await expect(
      assistantMessage.locator(".chat-bubble .katex-error"),
    ).toHaveCount(0);
    await expect(assistantMessage.locator(".chat-bubble")).not.toContainText(
      "###5.",
    );
  });

  test("assistant messages render normalized markdown tables", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.route(
      "**/api/v1/chat/conversations/*/messages",
      async (route, request) => {
        if (request.method() !== "POST") {
          await route.fallback();
          return;
        }

        const conversationId =
          request.url().match(/\/conversations\/([^/]+)\/messages$/)?.[1] ||
          "conv-001";
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "msg-table-fix-001",
            conversation_id: conversationId,
            role: "assistant",
            content:
              "## 理性总结\n| 步骤| 核心思想 | 局限性|\n|------|----------|--------|\n|德布罗意关系 | 波粒二象性 | 实验假设|\n|平面波假设 | 自由粒子模型 | 仅适用于自由态 |",
            reasoning_content: null,
            metadata_json: {},
            created_at: "2026-03-31T15:53:00.000Z",
          }),
        });
      },
    );

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await ensureChatConversationReady(page, handle.seedProjectId);
    await page.getByRole("textbox", { name: "输入消息…" }).fill("继续");
    await page.getByRole("button", { name: "发送" }).click();

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    await expect(
      assistantMessage.getByRole("heading", { name: "理性总结" }),
    ).toBeVisible();
    await expect(assistantMessage.locator(".chat-bubble table")).toBeVisible();
    await expect(assistantMessage.locator(".chat-bubble table")).toContainText(
      "核心思想",
    );
    await expect(assistantMessage.locator(".chat-bubble table")).toContainText(
      "德布罗意关系",
    );
    await expect(assistantMessage.locator(".chat-bubble table")).toContainText(
      "平面波假设",
    );
    await expect(assistantMessage.locator(".chat-bubble")).not.toContainText(
      "||------",
    );
  });

  test("assistant messages render normalized section labels, label-value rows, and bullet lists", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.route(
      "**/api/v1/chat/conversations/*/messages",
      async (route, request) => {
        if (request.method() !== "POST") {
          await route.fallback();
          return;
        }

        const conversationId =
          request.url().match(/\/conversations\/([^/]+)\/messages$/)?.[1] ||
          "conv-001";
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "msg-structure-fix-001",
            conversation_id: conversationId,
            role: "assistant",
            content:
              "薛定谔方程，一句话：它是量子力学的“牛顿第二定律”。\n\n核心要点：\n波函数 Ψ： 方程的解，代表粒子的“量子态”。\n\n关键优势：\n- 自动处理约束： 不用像牛顿力学那样硬算约束力。\n- 坐标无关性： 更适合广义坐标。",
            reasoning_content: null,
            metadata_json: {},
            created_at: "2026-04-01T14:20:00.000Z",
          }),
        });
      },
    );

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await ensureChatConversationReady(page, handle.seedProjectId);
    await page.getByRole("textbox", { name: "输入消息…" }).fill("继续");
    await page.getByRole("button", { name: "发送" }).click();

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    await expect
      .poll(async () =>
        assistantMessage
          .locator(".chat-bubble")
          .evaluate((node) => node.textContent || ""),
      )
      .toContain("薛定谔方程，一句话：它是量子力学的“牛顿第二定律”。");
    await expect
      .poll(async () =>
        assistantMessage
          .locator(".chat-bubble")
          .evaluate((node) => node.textContent || ""),
      )
      .toContain("核心要点：");
    await expect
      .poll(async () =>
        assistantMessage
          .locator(".chat-bubble")
          .evaluate((node) => node.textContent || ""),
      )
      .toContain("波函数 Ψ： 方程的解，代表粒子的“量子态”。");
    await expect
      .poll(async () =>
        assistantMessage
          .locator(".chat-bubble")
          .evaluate((node) => node.textContent || ""),
      )
      .toContain("关键优势：");
    await expect(assistantMessage.locator(".chat-bubble ul")).toBeVisible();
    await expect(assistantMessage.locator(".chat-bubble li")).toHaveCount(2);
    await expect(
      assistantMessage.locator(".chat-bubble li").first(),
    ).toContainText("自动处理约束： 不用像牛顿力学那样硬算约束力。");
    await expect(
      assistantMessage.locator(".chat-bubble li").nth(1),
    ).toContainText("坐标无关性： 更适合广义坐标。");
  });

  test("assistant messages recover broken emoji label blocks before rendering", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.route("**/api/v1/chat/conversations/*/stream", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          "event: message_start",
          'data: {"role":"assistant"}',
          "",
          "event: message_done",
          'data: {"id":"msg-emoji-label-fix-001","content":"下午好，董明阳！\\n🍵\\n深淬理论\\n：继续把狄拉克方程的能量变换，享受推导的快感？\\n🌳\\n校园漫步\\n：去海德公园（Hyde Park），或者南肯辛顿的博物馆区转转，寻找灵感？\\n💡\\n创意发散\\n：聊聊怎么把下午茶的悠闲和量子力学的烧脑结合起来？","reasoning_content":null}',
          "",
        ].join("\n"),
      });
    });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await ensureChatConversationReady(page, handle.seedProjectId);
    await page.getByRole("textbox", { name: "输入消息…" }).fill("继续");
    await page.getByRole("button", { name: "发送" }).click();

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    await expect(assistantMessage.locator(".chat-bubble")).toContainText(
      "🍵 深淬理论：继续把狄拉克方程的能量变换，享受推导的快感？",
    );
    await expect(assistantMessage.locator(".chat-bubble")).toContainText(
      "🌳 校园漫步：去海德公园（Hyde Park），或者南肯辛顿的博物馆区转转，寻找灵感？",
    );
    await expect(assistantMessage.locator(".chat-bubble")).toContainText(
      "💡 创意发散：聊聊怎么把下午茶的悠闲和量子力学的烧脑结合起来？",
    );
  });

  test("context trace stays hidden for none routes", async ({ page }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });
    await stubAssistantMessageWithRetrievalTrace(page, {
      strategy: "subject_graph_v1",
      context_level: "none",
      decision_source: "rules",
      decision_confidence: 1,
      memories: [],
      knowledge_chunks: [],
      linked_file_chunks: [],
    });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await ensureChatConversationReady(page, handle.seedProjectId);
    await page
      .getByRole("textbox", { name: "输入消息…" })
      .fill("介绍一下你自己");
    await page.getByRole("button", { name: "发送" }).click();

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    await expect(assistantMessage.locator(".chat-bubble")).toContainText(
      "Mock assistant response",
    );
    await expect(
      assistantMessage.locator(".chat-meta-chip--context"),
    ).toHaveCount(0);
  });

  test("profile-only routes surface a lightweight context chip", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });
    await stubAssistantMessageWithRetrievalTrace(page, {
      strategy: "subject_graph_v1",
      context_level: "profile_only",
      decision_source: "classifier",
      decision_confidence: 0.91,
      memories: [
        {
          id: "mem-001",
          type: "permanent",
          category: "用户画像",
          memory_kind: "profile",
          source: "static",
          score: 0.92,
          content: "用户偏好结构化解释。",
        },
      ],
      knowledge_chunks: [],
      linked_file_chunks: [],
    });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await ensureChatConversationReady(page, handle.seedProjectId);
    await page
      .getByRole("textbox", { name: "输入消息…" })
      .fill("你大概了解我什么");
    await page.getByRole("button", { name: "发送" }).click();

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    await expect(assistantMessage.locator(".chat-bubble")).toContainText(
      "Mock assistant response",
    );
    await expect(
      assistantMessage.locator(".chat-meta-chip--context"),
    ).toContainText("用了你的长期档案");
  });

  test("memory-only routes open the context inspector with memory sections only", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });
    await stubAssistantMessageWithRetrievalTrace(page, {
      strategy: "subject_graph_v1",
      context_level: "memory_only",
      decision_source: "rules",
      decision_confidence: 0.93,
      memories: [
        {
          id: "mem-002",
          type: "permanent",
          category: "偏好",
          memory_kind: "preference",
          source: "semantic",
          score: 0.94,
          salience: 0.87,
          content: "用户喜欢分步骤解释。",
        },
      ],
      knowledge_chunks: [],
      linked_file_chunks: [],
    });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await ensureChatConversationReady(page, handle.seedProjectId);
    await page
      .getByRole("textbox", { name: "输入消息…" })
      .fill("你记得我之前喜欢什么风格吗");
    await page.getByRole("button", { name: "发送" }).click();

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    const contextChip = assistantMessage.locator(".chat-meta-chip--context");
    await expect(contextChip).toContainText("参考了 1 条记忆");
    await contextChip.click();
    const inspector = page.locator(".chat-inspector-panel");
    await expect(inspector).toContainText("一贯信息");
    await expect(inspector).toContainText("用户喜欢分步骤解释。");
    await expect(inspector).not.toContainText("资料片段");
    await expect(inspector).not.toContainText("关联文件");
  });

  test("full-rag routes open grouped materials in the inspector", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });
    await stubAssistantMessageWithRetrievalTrace(page, {
      strategy: "subject_graph_v1",
      context_level: "full_rag",
      decision_source: "rules",
      decision_confidence: 0.95,
      memories: [
        {
          id: "mem-003",
          type: "permanent",
          category: "学习",
          memory_kind: "goal",
          source: "semantic",
          score: 0.91,
          content: "用户近期在准备数学竞赛。",
        },
      ],
      knowledge_chunks: [
        {
          id: "chunk-knowledge-001",
          filename: "数学手册.pdf",
          score: 0.89,
          chunk_text: "上传资料里给出了标准证明步骤。",
        },
      ],
      linked_file_chunks: [
        {
          id: "chunk-linked-001",
          filename: "竞赛笔记.md",
          score: 0.87,
          chunk_text: "记忆关联文件里记录了用户的练习偏好。",
        },
      ],
    });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await ensureChatConversationReady(page, handle.seedProjectId);
    await page
      .getByRole("textbox", { name: "输入消息…" })
      .fill("请结合我上传的资料回答");
    await page.getByRole("button", { name: "发送" }).click();

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    const contextChip = assistantMessage.locator(".chat-meta-chip--context");
    await expect(contextChip).toContainText("参考了 1 条记忆和 2 份资料");
    await contextChip.click();
    const inspector = page.locator(".chat-inspector-panel");
    await expect(inspector).toContainText("资料片段");
    await expect(inspector).toContainText("关联文件");
    await expect(inspector).toContainText("数学手册.pdf");
    await expect(inspector).toContainText("竞赛笔记.md");
  });

  test("context inspector surfaces V3 selection diagnostics from layered traces", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });
    await stubAssistantMessageWithRetrievalTrace(
      page,
      {
        strategy: "subject_graph_v1",
        context_level: "full_rag",
        decision_source: "planner",
        decision_confidence: 0.96,
        layer_hits: {
          profile: 0,
          durable_facts: 1,
          playbooks: 1,
          episodic_timeline: 1,
          raw_evidence: 1,
        },
        policy_flags: ["suppress_stale"],
        used_playbook_ids: ["view-playbook-001"],
        conflicted_memory_ids: ["mem-conflict-001"],
        episode_ids: ["episode-001"],
        memories: [
          {
            id: "mem-v3-001",
            type: "permanent",
            category: "排查流程",
            memory_kind: "fact",
            source: "semantic",
            score: 0.95,
            content: "先确认环境，再跑回归。",
            selection_reason: "匹配了当前问题的排查流程。",
            suppression_reason: "旧版本步骤已降权。",
            outcome_weight: 1.4,
            episode_ids: ["episode-001"],
          },
        ],
        view_hits: [
          {
            id: "view-playbook-001",
            view_type: "playbook",
            score: 0.9,
            content: "先确认环境，再跑回归。",
            snippet: "先确认环境，再跑回归。",
            selection_reason: "复用了最近成功的方法卡。",
            outcome_weight: 1.2,
          },
        ],
        evidence_hits: [
          {
            id: "evidence-001",
            source_type: "message",
            quote_text: "这套流程上次成功解决过同类问题。",
            snippet: "这套流程上次成功解决过同类问题。",
            score: 0.82,
            selection_reason: "提供原始经历证据。",
            episode_id: "episode-001",
          },
        ],
        knowledge_chunks: [],
        linked_file_chunks: [],
      },
      "基于记忆图谱给出建议。",
    );

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await ensureChatConversationReady(page, handle.seedProjectId);
    await page
      .getByRole("textbox", { name: "输入消息…" })
      .fill("给我一个排查建议");
    await page.getByRole("button", { name: "发送" }).click();

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    const contextChip = assistantMessage.locator(".chat-meta-chip--context");
    await contextChip.click();

    const inspector = page.locator(".chat-inspector-panel");
    await expect(inspector).toContainText("选择原因");
    await expect(inspector).toContainText("匹配了当前问题的排查流程。");
    await expect(inspector).toContainText("压制原因");
    await expect(inspector).toContainText("旧版本步骤已降权。");
    await expect(inspector).toContainText("结果权重");
    await expect(inspector).toContainText("1.4x");
    await expect(inspector).toContainText("方法卡");
    await expect(inspector).toContainText("view-playbook-001");
    await expect(inspector).toContainText("原始经历");
    await expect(inspector).toContainText("episode-001");
    await expect(inspector).toContainText("提供原始经历证据。");
  });

  test("chat updates remembered facts when assistant metadata arrives over the events stream", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.addInitScript(() => {
      class MockEventSource {
        url: string;
        withCredentials: boolean;
        onerror: ((event: Event) => void) | null = null;
        private listeners = new Map<
          string,
          Array<(event: MessageEvent<string>) => void>
        >();

        constructor(url: string | URL, init?: EventSourceInit) {
          this.url = String(url);
          this.withCredentials = Boolean(init?.withCredentials);

          if (
            this.url.includes(
              "/api/v1/chat/conversations/conv-memory-events/events",
            )
          ) {
            setTimeout(() => {
              const payload = {
                id: "msg-memory-001",
                metadata_json: {
                  memories_extracted: "新增永久记忆 1 条",
                  extracted_facts: [
                    {
                      fact: "用户对微分几何有持续兴趣",
                      category: "学习·兴趣",
                      importance: 0.95,
                      status: "permanent",
                      triage_action: "create",
                      triage_reason: "这是稳定且高重要度的长期偏好",
                    },
                  ],
                },
              };
              const callbacks =
                this.listeners.get("assistant_message_metadata") || [];
              for (const callback of callbacks) {
                callback(
                  new MessageEvent("assistant_message_metadata", {
                    data: JSON.stringify(payload),
                  }),
                );
              }
            }, 200);
          }
        }

        addEventListener(
          type: string,
          listener: EventListenerOrEventListenerObject,
        ) {
          const callback =
            typeof listener === "function"
              ? (listener as (event: MessageEvent<string>) => void)
              : (event: MessageEvent<string>) => listener.handleEvent(event);
          const existing = this.listeners.get(type) || [];
          existing.push(callback);
          this.listeners.set(type, existing);
        }

        removeEventListener(
          type: string,
          listener: EventListenerOrEventListenerObject,
        ) {
          const existing = this.listeners.get(type) || [];
          const callback =
            typeof listener === "function"
              ? (listener as (event: MessageEvent<string>) => void)
              : (event: MessageEvent<string>) => listener.handleEvent(event);
          this.listeners.set(
            type,
            existing.filter((item) => item !== callback),
          );
        }

        close() {
          return undefined;
        }
      }

      Object.defineProperty(window, "EventSource", {
        configurable: true,
        writable: true,
        value: MockEventSource,
      });

      Object.defineProperty(globalThis, "EventSource", {
        configurable: true,
        writable: true,
        value: MockEventSource,
      });
    });

    await page.route(
      `**/api/v1/chat/conversations?project_id=${handle.seedProjectId}`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              id: "conv-memory-events",
              project_id: handle.seedProjectId,
              title: "记忆事件测试",
              updated_at: "2026-03-14T12:00:00.000Z",
            },
          ]),
        });
      },
    );

    await page.route(
      "**/api/v1/chat/conversations/conv-memory-events/messages",
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              id: "msg-memory-001",
              conversation_id: "conv-memory-events",
              role: "assistant",
              content: "先正常回答，记忆稍后补上。",
              reasoning_content: null,
              metadata_json: {},
              created_at: "2026-03-14T12:00:00.000Z",
            },
          ]),
        });
      },
    );

    await page.goto(
      `/app/chat?project_id=${handle.seedProjectId}&conv=conv-memory-events`,
    );

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    await expect(assistantMessage.locator(".chat-bubble")).toContainText(
      "先正常回答，记忆稍后补上。",
    );
    await expect(assistantMessage.locator(".chat-memory-summary-card")).toContainText(
      "用户对微分几何有持续兴趣",
    );
    await assistantMessage.locator(".chat-memory-summary-open").click();
    const inspector = page.locator(".chat-inspector-panel");
    await expect(inspector).toContainText("用户对微分几何有持续兴趣");
    await expect(inspector).toContainText("长期档案");
    await expect(inspector).toContainText("这是稳定且高重要度的长期偏好");
  });

  test("new assistant messages render with a typewriter cursor before settling", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await ensureChatConversationReady(page, handle.seedProjectId);
    await page.getByRole("textbox", { name: "输入消息…" }).fill("帮我起草");
    await page.getByRole("button", { name: "发送" }).click();

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    await expect(assistantMessage.locator(".chat-inline-cursor")).toBeVisible();
    await expect(assistantMessage.locator(".chat-bubble")).toContainText(
      "Mock assistant response",
    );
  });

  test("memory inspector fetches details on demand and refreshes after edit, promote, and delete", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });
    let detailGets = 0;
    let currentContent = "用户准备继续学习微分几何。";
    let currentType: "temporary" | "permanent" = "temporary";

    await page.route(
      "**/api/v1/chat/conversations/*/messages",
      async (route, request) => {
        if (request.method() !== "POST") {
          await route.fallback();
          return;
        }

        const conversationId =
          request.url().match(/\/conversations\/([^/]+)\/messages$/)?.[1] ||
          "conv-001";
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "msg-memory-govern-001",
            conversation_id: conversationId,
            role: "assistant",
            content: "先给出正常回答，再把记忆放到 inspector。",
            reasoning_content: null,
            metadata_json: {
              extracted_facts: [
                {
                  fact: currentContent,
                  category: "学习计划",
                  importance: 0.93,
                  status: "temporary",
                  triage_action: "create",
                  triage_reason: "这是当前轮的短期计划。",
                  target_memory_id: "memory-temp-001",
                },
              ],
            },
            created_at: "2026-03-14T12:00:00.000Z",
          }),
        });
      },
    );

    await page.route("**/api/v1/memory/memory-temp-001", async (route) => {
      if (route.request().method() === "GET") {
        detailGets += 1;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "memory-temp-001",
            content: currentContent,
            category: "学习计划",
            type: currentType,
            metadata_json: {},
          }),
        });
        return;
      }

      if (route.request().method() === "PATCH") {
        const body = route.request().postDataJSON() as { content?: string };
        currentContent = body.content || currentContent;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "memory-temp-001",
            content: currentContent,
            category: "学习计划",
            type: currentType,
            metadata_json: {},
          }),
        });
        return;
      }

      if (route.request().method() === "DELETE") {
        await route.fulfill({
          status: 204,
          body: "",
        });
        return;
      }

      await route.fallback();
    });

    await page.route(
      "**/api/v1/memory/memory-temp-001/promote",
      async (route) => {
        currentType = "permanent";
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "memory-temp-001",
            content: currentContent,
            category: "学习计划",
            type: currentType,
            metadata_json: {},
          }),
        });
      },
    );

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await ensureChatConversationReady(page, handle.seedProjectId);
    await page.getByRole("textbox", { name: "输入消息…" }).fill("记一下");
    await page.getByRole("button", { name: "发送" }).click();

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    const memoryCard = assistantMessage.locator(".chat-memory-summary-card");
    await expect(memoryCard).toContainText("记住了");
    await expect(memoryCard).toContainText("新增临时记忆 1 条");
    await assistantMessage.locator(".chat-memory-summary-open").click();

    const inspector = page.locator(".chat-inspector-panel");
    await expect(inspector).toContainText("这是当前轮的短期计划。");
    expect(detailGets).toBe(0);

    await inspector.getByRole("button", { name: "展开" }).click();
    await expect.poll(() => detailGets).toBe(1);
    await expect(inspector).toContainText("memory-temp-001");

    await inspector.getByRole("button", { name: "编辑内容" }).click();
    await inspector
      .locator(".chat-memory-write-textarea")
      .fill("用户准备继续学习微分几何和李群。");
    await inspector.getByRole("button", { name: "保存" }).click();
    await expect(inspector).toContainText("李群");
    await expect(memoryCard).toContainText("李群");

    await inspector.getByRole("button", { name: "升为长期" }).click();
    await expect(inspector).toContainText("长期档案");

    await inspector.getByRole("button", { name: "删除" }).click();
    await expect(inspector).toContainText("这轮没有写入记忆");
    await expect(memoryCard).toHaveCount(0);
  });

  test("mobile inspector opens as a bottom sheet", async ({ page }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.setViewportSize({ width: 390, height: 844 });
    await stubAssistantMessageWithRetrievalTrace(page, {
      strategy: "subject_graph_v1",
      context_level: "full_rag",
      memories: [
        {
          id: "mem-mobile-001",
          type: "permanent",
          category: "用户画像",
          memory_kind: "profile",
          source: "static",
          score: 0.92,
          content: "用户偏好条理清晰的答案。",
        },
      ],
      knowledge_chunks: [
        {
          id: "chunk-mobile-001",
          filename: "指南.pdf",
          score: 0.81,
          chunk_text: "这里有一段知识库片段。",
        },
      ],
      linked_file_chunks: [],
    });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await page.getByRole("textbox", { name: "输入消息…" }).fill("移动端看看");
    await page.getByRole("button", { name: "发送" }).click();

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    await assistantMessage.locator(".chat-meta-chip--context").click();
    await expect(page.locator(".chat-inspector-sheet")).toBeVisible();
    await expect(page.locator(".chat-inspector-sheet")).toContainText(
      "指南.pdf",
    );
  });

  test("auto read requests speech for each new assistant reply", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });
    const speechBodies: Array<{ content?: string }> = [];

    await stubBrowserVoiceApis(page);
    await page.route("**/api/v1/chat/conversations/*/speech", async (route) => {
      speechBodies.push(route.request().postDataJSON() as { content?: string });
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          audio_response: "AQID",
        }),
      });
    });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await openChatToolsMenu(page);
    await page
      .locator(".chat-tools-menu-item", { hasText: "自动朗读" })
      .click();
    await expect(page.locator(".chat-active-tool")).toContainText("自动朗读");
    await page
      .getByRole("textbox", { name: "输入消息…" })
      .fill("请自动朗读这段回复");
    await page.getByRole("button", { name: "发送" }).click();

    await expect.poll(() => speechBodies.length).toBe(1);
    expect(speechBodies[0]).toEqual({ content: "Mock assistant response" });
  });

  test("standard chat can send an image through the image pipeline", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });
    let imageCalls = 0;

    await page.route("**/api/v1/chat/conversations/*/image", async (route) => {
      imageCalls += 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          message: {
            id: "msg-image-1",
            role: "assistant",
            content: "Mock image response",
            created_at: "2026-03-18T08:00:00.000Z",
          },
          text_input: "请描述这张图片",
          audio_response: "AQID",
        }),
      });
    });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await openChatToolsMenu(page);
    await expect(
      page.locator(".chat-tools-menu-item", { hasText: "添加图片" }),
    ).toBeVisible();
    await page
      .locator('[data-testid="chat-image-upload-input"]:not([disabled])')
      .setInputFiles({
        name: "demo.png",
        mimeType: "image/png",
        buffer: Buffer.from("fake-image"),
      });

    await expect(page.locator(".chat-attachment-chip")).toContainText(
      "demo.png",
    );
    await page.getByRole("button", { name: "发送" }).click();

    await expect.poll(() => imageCalls).toBe(1);
    await expect(
      page.locator(".chat-message.is-assistant").last(),
    ).toContainText("Mock image response");
  });

  test("chat mode overrides stay scoped to the current conversation", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.route(
      `**/api/v1/chat/conversations?project_id=${handle.seedProjectId}`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              id: "conv-a",
              project_id: handle.seedProjectId,
              title: "会话 A",
              updated_at: "2026-03-18T08:00:00.000Z",
            },
            {
              id: "conv-b",
              project_id: handle.seedProjectId,
              title: "会话 B",
              updated_at: "2026-03-18T07:00:00.000Z",
            },
          ]),
        });
      },
    );

    await page.route(
      "**/api/v1/chat/conversations/conv-a/messages",
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        });
      },
    );

    await page.route(
      "**/api/v1/chat/conversations/conv-b/messages",
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        });
      },
    );

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await page.getByRole("button", { name: "合成实时" }).click();
    await expect(page.getByRole("button", { name: "合成实时" })).toHaveClass(
      /is-active/,
    );

    await page
      .locator(".chat-sidebar-item")
      .filter({ hasText: "会话 B" })
      .click();
    await expect(page.getByRole("button", { name: "普通对话" })).toHaveClass(
      /is-active/,
    );
  });

  test("chat history selection survives conversation list reloads", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });
    const conversations = [
      {
        id: "conv-empty",
        project_id: handle.seedProjectId,
        title: "空白会话",
        updated_at: "2026-03-18T08:00:00.000Z",
      },
      {
        id: "conv-history",
        project_id: handle.seedProjectId,
        title: "1天前",
        updated_at: "2026-03-17T08:00:00.000Z",
      },
    ];

    await page.route(
      `**/api/v1/chat/conversations?project_id=${handle.seedProjectId}`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(conversations),
        });
      },
    );

    await page.route(
      "**/api/v1/chat/conversations/conv-empty/messages",
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        });
      },
    );

    await page.route(
      "**/api/v1/chat/conversations/conv-history/messages",
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              id: "msg-1",
              role: "user",
              content: "历史问题",
              created_at: "2026-03-17T08:00:00.000Z",
            },
            {
              id: "msg-2",
              role: "assistant",
              content: "历史回复",
              created_at: "2026-03-17T08:00:30.000Z",
            },
          ]),
        });
      },
    );

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await page.locator(".chat-sidebar-item").nth(1).click();
    await expect(
      page.locator(".chat-message.is-assistant").last(),
    ).toContainText("历史回复");

    await page.evaluate(() => {
      const select = document.querySelector(
        ".inline-topbar-project-select",
      ) as HTMLSelectElement | null;
      select?.dispatchEvent(new Event("change", { bubbles: true }));
    });

    await expect(
      page.locator(".chat-message.is-assistant").last(),
    ).toContainText("历史回复");
  });

  test("assistant detail settings dialog saves edited identity", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });
    let patchedProject:
      | {
          name?: string;
          description?: string;
        }
      | undefined;

    await page.route(
      `**/api/v1/projects/${handle.seedProjectId}`,
      async (route) => {
        if (route.request().method().toUpperCase() !== "PATCH") {
          await route.fallback();
          return;
        }

        patchedProject = route.request().postDataJSON() as {
          name?: string;
          description?: string;
        };
        await route.fallback();
      },
    );

    await page.goto(`/app/assistants/${handle.seedProjectId}`);
    await page
      .locator(".assistant-profile-actions")
      .getByRole("button", { name: "设置" })
      .click();

    await expect(page.getByRole("dialog")).toBeVisible();
    await page.getByLabel("助手名字").fill("更新后的助手");
    await page.getByRole("button", { name: "保存" }).click();

    await expect(page.getByRole("dialog")).not.toBeVisible();
    await expect(
      page.getByRole("heading", { name: "更新后的助手" }),
    ).toBeVisible();
    expect(patchedProject).toMatchObject({
      name: "更新后的助手",
    });
  });

  test("assistant detail model picker updates the visible llm name", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/assistants/${handle.seedProjectId}`);
    await expect(page.locator(".profile-model-name").first()).toHaveText(
      "Qwen 3.5 Plus",
    );

    await page.locator(".profile-model-change").first().click();
    await expect(page.locator(".model-picker-card")).toBeVisible();

    const qwenMaxCard = page
      .locator(".model-picker-item")
      .filter({ hasText: "Qwen Max" })
      .first();
    await qwenMaxCard.locator(".marketplace-card-btn").click();

    await expect(page.locator(".profile-model-name").first()).toHaveText(
      "Qwen Max",
    );
  });

  test("assistant detail keeps the vision row visible in standard mode", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/assistants/${handle.seedProjectId}`);
    await page.getByRole("button", { name: "模型" }).click();

    const visionRow = page
      .locator(".profile-model-row")
      .filter({ hasText: "视觉理解" })
      .first();
    await expect(visionRow).toBeVisible();
    await expect(visionRow).toContainText("Qwen 3.5 Plus");
  });

  test("assistants page filters cards by the selected project", async ({
    page,
  }) => {
    await installWorkbenchApiMock(page, { authenticated: true });
    await setPlaywrightProjects(page, [
      {
        id: "proj-seed",
        name: "Seed Console Project",
      },
      {
        id: "proj-test-a",
        name: "测试项目A",
      },
      {
        id: "proj-doctor",
        name: "医生",
      },
    ]);

    await page.goto("/app/assistants");
    await page
      .locator(".inline-topbar-project-select")
      .selectOption("proj-test-a");

    await expect(page.locator(".assistant-card-name")).toHaveCount(1);
    await expect(page.locator(".assistant-card-name").first()).toHaveText(
      "测试项目A",
    );
  });

  test("duplicate project names stay distinguishable in selectors", async ({
    page,
  }) => {
    await installWorkbenchApiMock(page, { authenticated: true });
    await setPlaywrightProjects(page, [
      {
        id: "11111111-aaaa-4aaa-8aaa-111111111111",
        name: "测试项目A",
      },
      {
        id: "22222222-bbbb-4bbb-8bbb-222222222222",
        name: "测试项目A",
      },
    ]);

    await page.goto("/app/assistants");
    await expect(page.locator(".inline-topbar-project-select")).toBeVisible();
    await expect(page.locator(".inline-topbar-project-select")).toContainText(
      "测试项目A (11111111)",
    );
    await expect(page.locator(".inline-topbar-project-select")).toContainText(
      "测试项目A (22222222)",
    );
  });

  test("memory graph stats reflect the filtered search results", async ({
    page,
  }) => {
    test.slow();
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.route(
      /\/api\/v1\/memory(?:\?.*)?$/,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            nodes: [
              {
                id: "memory-root",
                workspace_id: handle.workspaceId,
                project_id: handle.seedProjectId,
                content: "Seed Console Project",
                category: "assistant",
                type: "permanent",
                source_conversation_id: null,
                parent_memory_id: null,
                position_x: 0,
                position_y: 0,
                metadata_json: {
                  node_kind: "assistant-root",
                  assistant_name: "Seed Console Project",
                },
                created_at: "2026-03-18T08:00:00.000Z",
                updated_at: "2026-03-18T08:00:00.000Z",
              },
              {
                id: "memory-1",
                workspace_id: handle.workspaceId,
                project_id: handle.seedProjectId,
                content: "心理咨询流程",
                category: "心理",
                type: "permanent",
                source_conversation_id: null,
                parent_memory_id: "memory-root",
                position_x: 0,
                position_y: 0,
                metadata_json: {},
                created_at: "2026-03-18T08:00:00.000Z",
                updated_at: "2026-03-18T08:00:00.000Z",
              },
              {
                id: "memory-2",
                workspace_id: handle.workspaceId,
                project_id: handle.seedProjectId,
                content: "心理干预记录",
                category: "心理",
                type: "permanent",
                source_conversation_id: null,
                parent_memory_id: "memory-root",
                position_x: 60,
                position_y: 40,
                metadata_json: {},
                created_at: "2026-03-18T08:00:00.000Z",
                updated_at: "2026-03-18T08:00:00.000Z",
              },
              {
                id: "memory-3",
                workspace_id: handle.workspaceId,
                project_id: handle.seedProjectId,
                content: "医生排班安排",
                category: "医生",
                type: "permanent",
                source_conversation_id: null,
                parent_memory_id: "memory-root",
                position_x: -40,
                position_y: -30,
                metadata_json: {},
                created_at: "2026-03-18T08:00:00.000Z",
                updated_at: "2026-03-18T08:00:00.000Z",
              },
            ],
            edges: [],
          }),
        });
      },
    );

    await page.goto(`/app/memory`);
    await page.getByPlaceholder("搜索记忆…").fill("心理");
    await expect(page.locator(".graph-controls-stats")).toContainText(
      "共 2 个记忆",
    );
  });

  test("memory page count excludes the assistant root memory node", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.route(
      `**/api/v1/memory?project_id=${handle.seedProjectId}`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            nodes: [
              {
                id: "memory-root",
                workspace_id: handle.workspaceId,
                project_id: handle.seedProjectId,
                content: "医生助手",
                category: "assistant",
                type: "permanent",
                source_conversation_id: null,
                parent_memory_id: null,
                position_x: 0,
                position_y: 0,
                metadata_json: {
                  node_kind: "assistant-root",
                  assistant_name: "医生助手",
                },
                created_at: "2026-03-18T08:00:00.000Z",
                updated_at: "2026-03-18T08:00:00.000Z",
              },
              {
                id: "memory-1",
                workspace_id: handle.workspaceId,
                project_id: handle.seedProjectId,
                content: "用户偏好午后回访",
                category: "偏好",
                type: "permanent",
                source_conversation_id: null,
                parent_memory_id: "memory-root",
                position_x: 32,
                position_y: 16,
                metadata_json: {},
                created_at: "2026-03-18T08:00:00.000Z",
                updated_at: "2026-03-18T08:00:00.000Z",
              },
            ],
            edges: [],
          }),
        });
      },
    );

    await page.goto(`/app/memory`);
    await expect(page.locator(".memory-topbar-count")).toContainText("1");
    await page.getByRole("button", { name: "列表" }).click();
    await expect(page.locator(".memory-list-item")).toHaveCount(1);
    await expect(page.locator(".memory-list-item")).toContainText(
      "用户偏好午后回访",
    );
  });

  test("memory detail panel reflects promote immediately without reopening", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, {
      authenticated: true,
      seedMemoryNodes: [
        {
          id: "memory-temp-detail",
          project_id: "proj-seed",
          content: "用户下周去东京出差",
          category: "工作.计划",
          type: "temporary",
          source_conversation_id: "conv-temp-detail",
          parent_memory_id: "memory-root-seed",
          position_x: 24,
          position_y: 18,
          metadata_json: {},
          created_at: "2026-03-18T08:00:00.000Z",
          updated_at: "2026-03-18T08:00:00.000Z",
        },
      ],
    });

    await page.goto(`/app/memory?project_id=${handle.seedProjectId}`);
    await page.locator(".mem-view-switcher .mem-view-btn").nth(1).click();
    await expect(page.locator(".mem-list-row")).toHaveCount(1);
    await page
      .locator(".mem-list-row")
      .filter({ hasText: "用户下周去东京出差" })
      .click();

    const detail = page.locator(".mem-detail");
    await expect(detail).toContainText("临时");
    await detail.getByRole("button", { name: "升级为永久" }).click();
    await expect(detail).toContainText("永久");
    await expect(
      detail.getByRole("button", { name: "升级为永久" }),
    ).toHaveCount(0);
  });

  test("memory detail panel surfaces V3 diagnostics and episode context", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, {
      authenticated: true,
      seedMemoryNodes: [
        {
          id: "memory-detail-v3",
          project_id: "proj-seed",
          content: "用户要求周报先给摘要，再给细节",
          category: "偏好.沟通",
          type: "permanent",
          source_conversation_id: "conv-detail-v3",
          parent_memory_id: "memory-root-seed",
          position_x: 18,
          position_y: 26,
          metadata_json: {},
          created_at: "2026-03-18T08:00:00.000Z",
          updated_at: "2026-03-18T08:00:00.000Z",
        },
      ],
    });

    await page.route("**/api/v1/memory/memory-detail-v3", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "memory-detail-v3",
          content: "用户要求周报先给摘要，再给细节",
          category: "偏好.沟通",
          type: "permanent",
          confidence: 0.94,
          observed_at: "2026-03-12T09:00:00.000Z",
          valid_from: "2026-03-12T09:00:00.000Z",
          valid_to: "2026-05-12T09:00:00.000Z",
          last_confirmed_at: "2026-03-20T08:00:00.000Z",
          suppression_reason: "等待用户重新确认最新周报格式。",
          reconfirm_after: "2026-05-01T08:00:00.000Z",
          last_used_at: "2026-03-21T08:00:00.000Z",
          reuse_success_rate: 0.8,
          evidences: [
            {
              id: "evidence-detail-v3",
              quote_text: "用户说：周报先给摘要，再展开细节。",
              source_type: "message",
              confidence: 0.97,
              created_at: "2026-03-12T09:00:00.000Z",
            },
          ],
          episodes: [
            {
              id: "episode-detail-v3",
              source_type: "message",
              chunk_text: "用户在晨会里明确要求周报先给摘要。",
              created_at: "2026-03-12T09:00:00.000Z",
            },
          ],
          views: [
            {
              id: "view-detail-v3",
              view_type: "playbook",
              content: "先给摘要，再补充细节。",
            },
          ],
          timeline_events: [
            {
              id: "timeline-detail-v3",
              content: "2026 年 3 月确认周报结构",
              observed_at: "2026-03-12T09:00:00.000Z",
              node_status: "active",
            },
          ],
          write_history: [
            {
              id: "write-detail-v3",
              decision: "write",
              reason: "用户明确表达了长期偏好",
              created_at: "2026-03-12T09:00:00.000Z",
            },
          ],
          learning_history: [
            {
              id: "learning-detail-v3",
              trigger: "post_turn",
              status: "completed",
              stages: ["observe", "reflect", "reuse"],
              created_at: "2026-03-21T08:00:00.000Z",
            },
          ],
        }),
      });
    });

    await page.goto(`/app/memory?project_id=${handle.seedProjectId}`);
    await page.locator(".mem-view-switcher .mem-view-btn").nth(1).click();
    await page
      .locator(".mem-list-row")
      .filter({ hasText: "用户要求周报先给摘要" })
      .click();

    const detail = page.locator(".mem-detail");
    await expect(detail).toContainText("压制原因");
    await expect(detail).toContainText("等待用户重新确认最新周报格式。");
    await expect(detail).toContainText("复用成功率");
    await expect(detail).toContainText("80%");
    await expect(detail).toContainText("原始经历");
    await expect(detail).toContainText("用户在晨会里明确要求周报先给摘要。");

    await detail.getByRole("button", { name: "学习记录" }).click();
    await expect(detail).toContainText("observe -> reflect -> reuse");
  });

  test("memory workbench surfaces learning and health panels", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, {
      authenticated: true,
      seedMemoryNodes: [
        {
          id: "memory-learning-panel-1",
          project_id: "proj-seed",
          workspace_id: "ws-playwright",
          content: "用户喜欢晚间复盘",
          category: "偏好.习惯",
          type: "permanent",
          source_conversation_id: null,
          parent_memory_id: "memory-root-seed",
          position_x: 30,
          position_y: 22,
          metadata_json: {},
          created_at: "2026-03-18T08:00:00.000Z",
          updated_at: "2026-03-18T08:00:00.000Z",
        },
      ],
      seedMemoryLearningRuns: [
        {
          id: "learning-run-1",
          project_id: "proj-seed",
          trigger: "post_turn",
          status: "completed",
          stages: ["observe", "extract", "consolidate", "graphify"],
          used_memory_ids: ["memory-learning-panel-1"],
          promoted_memory_ids: ["memory-learning-panel-1"],
          degraded_memory_ids: ["memory-learning-panel-1"],
          outcome_id: "outcome-1",
          completed_at: "2026-03-18T08:10:00.000Z",
        },
      ],
      seedMemoryHealth: {
        "proj-seed": {
          counts: { stale: 1, high_risk_playbook: 1 },
          entries: [
            {
              kind: "stale",
              reason: "needs reconfirm",
              memory: {
                id: "memory-learning-panel-1",
                workspace_id: "ws-playwright",
                project_id: "proj-seed",
                content: "用户喜欢晚间复盘",
                category: "偏好.习惯",
                type: "permanent",
                source_conversation_id: null,
                parent_memory_id: "memory-root-seed",
                position_x: 30,
                position_y: 22,
                metadata_json: {},
                created_at: "2026-03-18T08:00:00.000Z",
                updated_at: "2026-03-18T08:00:00.000Z",
              },
            },
            {
              kind: "high_risk_playbook",
              reason: "playbook failures exceed successes",
              view: {
                id: "view-health-risk-1",
                view_type: "playbook",
                content: "晚间复盘流程",
                source_subject_id: "memory-learning-panel-1",
                updated_at: "2026-03-18T08:20:00.000Z",
                metadata_json: {
                  success_count: 1,
                  failure_count: 3,
                  common_failure_reasons: ["timeout", "missing context"],
                },
              },
            },
          ],
        },
      },
      seedMemoryDetails: {
        "memory-learning-panel-1": {
          id: "memory-learning-panel-1",
          workspace_id: "ws-playwright",
          project_id: "proj-seed",
          content: "用户喜欢晚间复盘",
          category: "偏好.习惯",
          type: "permanent",
          source_conversation_id: null,
          parent_memory_id: "memory-root-seed",
          position_x: 30,
          position_y: 22,
          metadata_json: {},
          created_at: "2026-03-18T08:00:00.000Z",
          updated_at: "2026-03-18T08:00:00.000Z",
          views: [
            {
              id: "view-health-risk-1",
              view_type: "playbook",
              content: "1. 先检查复盘上下文\n2. 再拉取最近任务\n3. 最后补全缺失信息",
            },
          ],
          learning_history: [
            {
              id: "learning-run-1",
              trigger: "post_turn",
              status: "completed",
              stages: ["observe", "extract", "consolidate", "graphify"],
              created_at: "2026-03-18T08:10:00.000Z",
            },
          ],
        },
      },
    });

    await page.goto(`/app/memory?project_id=${handle.seedProjectId}`);

    await page.locator(".mem-view-switcher .mem-view-btn").nth(4).click();
    await expect(page.locator(".mem-layer-summary-card").first()).toContainText("学习运行");
    await expect(page.locator(".mem-layer-card")).toContainText("已关联结果");
    await expect(page.locator(".mem-layer-card")).toContainText("命中 1");
    await expect(page.locator(".mem-layer-card")).toContainText("降权 1");
    await expect(page.locator(".mem-layer-card")).toContainText("post_turn");
    await expect(page.locator(".mem-layer-card")).toContainText(
      "用户喜欢晚间复盘",
    );
    await page.getByRole("button", { name: "用户喜欢晚间复盘" }).click();
    await expect(page.locator(".mem-detail")).toContainText(
      "observe -> extract -> consolidate -> graphify",
    );
    await page.locator(".mem-detail-close").click();
    await expect(page.locator(".mem-detail")).toHaveCount(0);

    await page.locator(".mem-view-switcher .mem-view-btn").nth(5).click();
    await expect(
      page.locator(".mem-layer-chiprow").filter({ hasText: "高风险方法卡 1" }).first(),
    ).toContainText("高风险方法卡 1");
    await expect(
      page.locator(".mem-layer-card").filter({ hasText: "过期" }).first(),
    ).toContainText(
      "needs reconfirm",
    );
    await expect(
      page.locator(".mem-layer-card").filter({ hasText: "高风险方法卡" }).first(),
    ).toContainText("成功/失败");
    await expect(
      page.locator(".mem-layer-card").filter({ hasText: "高风险方法卡" }).first(),
    ).toContainText("1/3");
    await expect(
      page.locator(".mem-layer-card").filter({ hasText: "高风险方法卡" }).first(),
    ).toContainText("timeout");
    await page
      .locator(".mem-layer-card")
      .filter({ hasText: "高风险方法卡" })
      .first()
      .click();
    await expect(page.locator(".mem-detail")).toContainText(
      "1. 先检查复盘上下文",
    );
  });

  test("assistant detail breadcrumbs use the assistant name instead of a raw uuid", async ({
    page,
  }) => {
    await installWorkbenchApiMock(page, { authenticated: true });
    const projectId = "f555d613-aaaa-4a15-8fd5-100000000001";
    await setPlaywrightProjects(page, [
      {
        id: projectId,
        name: "医生",
      },
    ]);

    await page.goto(`/app/assistants/${projectId}`);
    await expect(page.locator(".inline-topbar-breadcrumb")).toContainText(
      "医生",
    );
    await expect(page.locator(".inline-topbar-breadcrumb")).not.toContainText(
      "f555d613",
    );
  });

  test("assistant knowledge manager stays localized in Chinese", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/assistants/${handle.seedProjectId}`);
    await page.getByRole("button", { name: "管理" }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("教它知识");
    await expect(dialog).toContainText("拖拽文件到此处，或点击选择文件");
    await expect(dialog).toContainText("支持 PDF、TXT、DOCX、MD 格式");
  });

  test("chat generic failures stay localized in Chinese", async ({ page }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.route(
      "**/api/v1/chat/conversations/*/messages",
      async (route) => {
        if (route.request().method().toUpperCase() !== "POST") {
          await route.fallback();
          return;
        }

        await route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({
            error: {
              code: "unexpected_failure",
              message: "Sorry, something went wrong",
            },
          }),
        });
      },
    );

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await page.locator(".chat-sidebar-new").click();
    await page.getByRole("textbox", { name: "输入消息…" }).fill("测试报错");
    await page.getByRole("button", { name: "发送" }).click();

    await expect(
      page.locator(".chat-message.is-assistant").last(),
    ).toContainText("抱歉，刚才出错了，请重试。");
  });

  test("model marketplace detail buttons stay on one line", async ({
    page,
  }) => {
    await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto("/app");
    const hasNowrapRule = await page.evaluate(() => {
      return Array.from(document.styleSheets).some((sheet) => {
        try {
          return Array.from(sheet.cssRules).some((rule) => {
            return (
              rule.cssText.includes(".marketplace-card-btn") &&
              rule.cssText.includes("white-space: nowrap")
            );
          });
        } catch {
          return false;
        }
      });
    });
    expect(hasNowrapRule).toBe(true);
  });

  test("chat sidebar falls back to a message summary when the conversation title is empty", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.route(
      `**/api/v1/chat/conversations?project_id=${handle.seedProjectId}`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              id: "conv-summary",
              project_id: handle.seedProjectId,
              title: "",
              updated_at: "2026-03-17T08:00:00.000Z",
            },
          ]),
        });
      },
    );

    await page.route(
      "**/api/v1/chat/conversations/conv-summary/messages",
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              id: "msg-user",
              role: "user",
              content: "如何缓解焦虑和失眠？",
              created_at: "2026-03-17T08:00:00.000Z",
            },
            {
              id: "msg-assistant",
              role: "assistant",
              content: "可以先从睡眠节律和情绪记录开始。",
              created_at: "2026-03-17T08:01:00.000Z",
            },
          ]),
        });
      },
    );

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await expect(
      page.locator(".chat-sidebar-item-title").first(),
    ).toContainText("如何缓解焦虑和失眠");
    await expect(page.locator(".chat-sidebar-item-time").first()).toContainText(
      /\d+天前/,
    );
  });

  test("double clicking the global chat nav does not leave an overlay over the conversation pane", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    const conversationItem = page.locator(".chat-sidebar-item").first();
    await expect(conversationItem).toBeVisible();

    const before = await page.evaluate(() => {
      const sidebar = document.querySelector(".chat-sidebar");
      const main = document.querySelector(".chat-main");
      const readRect = (element: Element | null) => {
        if (!element) {
          return null;
        }
        const box = element.getBoundingClientRect();
        return {
          x: Math.round(box.x),
          y: Math.round(box.y),
          width: Math.round(box.width),
          height: Math.round(box.height),
        };
      };
      return {
        sidebar: readRect(sidebar),
        main: readRect(main),
      };
    });

    await page
      .locator(".glass-sidebar--collapsed .glass-sidebar-nav-item")
      .nth(1)
      .dblclick();
    await page.waitForTimeout(250);

    await expect(page.locator(".glass-sidebar--expanded")).toHaveCount(0);

    const afterNavDblClick = await page.evaluate(() => {
      const sidebar = document.querySelector(".chat-sidebar");
      const main = document.querySelector(".chat-main");
      const readRect = (element: Element | null) => {
        if (!element) {
          return null;
        }
        const box = element.getBoundingClientRect();
        return {
          x: Math.round(box.x),
          y: Math.round(box.y),
          width: Math.round(box.width),
          height: Math.round(box.height),
        };
      };
      return {
        sidebar: readRect(sidebar),
        main: readRect(main),
      };
    });

    expect(afterNavDblClick.sidebar).toEqual(before.sidebar);
    expect(afterNavDblClick.main).toEqual(before.main);

    await conversationItem.click({ button: "right" });
    await expect(
      page.locator(".chat-sidebar-context-item.is-danger"),
    ).toBeVisible();

    const contextMenuState = await page.evaluate(() => {
      const menu = document.querySelector(".chat-sidebar-context-menu");
      const button = document.querySelector(
        ".chat-sidebar-context-item.is-danger",
      );
      const composer = document.querySelector(".chat-input-bar");
      const rect = (element: Element | null) => {
        if (!element) {
          return null;
        }
        const box = element.getBoundingClientRect();
        return {
          x: Math.round(box.x),
          y: Math.round(box.y),
          width: Math.round(box.width),
          height: Math.round(box.height),
        };
      };

      let menuHitTarget = null;
      if (button) {
        const box = button.getBoundingClientRect();
        const hit = document.elementFromPoint(
          box.left + box.width / 2,
          box.top + box.height / 2,
        );
        menuHitTarget =
          hit?.closest(".chat-sidebar-context-menu")?.className ||
          hit?.className ||
          null;
      }

      return {
        menu: rect(menu),
        composer: rect(composer),
        menuHitTarget,
      };
    });

    expect(contextMenuState.menuHitTarget).toBe("chat-sidebar-context-menu");
    expect(contextMenuState.menu?.y).not.toBeNull();
    expect(contextMenuState.composer?.y).not.toBeNull();
    expect(
      contextMenuState.menu!.y + contextMenuState.menu!.height,
    ).toBeLessThan(contextMenuState.composer!.y);
  });

  test("chat auto-creates a ready conversation when the assistant has no history", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await expect(page.locator(".chat-main .chat-empty").first()).toContainText(
      "新对话已创建，输入第一条消息开始测试",
    );
    const modeSwitcher = page.locator(".chat-mode-switcher").first();
    await expect(
      modeSwitcher.locator(".chat-mode-chip.is-active"),
    ).toContainText("普通对话");
    await expect(
      page.getByRole("textbox", { name: "输入消息…" }),
    ).toBeEnabled();
    await expect(page.locator(".chat-mic-btn").first()).toBeEnabled();
    await expect(page.locator(".rt-entry")).toHaveCount(0);
  });

  test("chat workspace toolbar reflects the active mode and message count", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    const toolbarState = page.getByTestId("chat-toolbar-state").first();
    await expect(toolbarState).toContainText("普通对话");
    await expect(toolbarState).toContainText("0 条消息");
  });

  test("chat initializes mode from the assistant default mode", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.route(
      `**/api/v1/projects/${handle.seedProjectId}`,
      async (route) => {
        if (route.request().method().toUpperCase() !== "GET") {
          await route.fallback();
          return;
        }

        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: handle.seedProjectId,
            name: "Seed Console Project",
            description: "Default workspace project",
            default_chat_mode: "synthetic_realtime",
            created_at: "2026-03-14T12:00:00.000Z",
          }),
        });
      },
    );

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    const modeSwitcher = page.locator(".chat-mode-switcher").first();
    await expect(
      modeSwitcher.locator(".chat-mode-chip.is-active"),
    ).toContainText("合成实时");
    await expect(page.locator(".chat-mic-btn")).toHaveCount(0);
    await expect(page.locator(".rt-entry")).toContainText("合成实时");
  });

  test("discover picker routes return to the source page when disabled", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(
      `/app/discover?picker=1&category=vision&current_model_id=qwen3-vl-plus&from=/app/assistants/${handle.seedProjectId}`,
    );

    await expect(page).toHaveURL(
      new RegExp(`/app/assistants/${handle.seedProjectId}$`),
    );
  });

  test("chat does not create a new conversation before existing history finishes loading", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });
    let createConversationCalls = 0;

    await page.route("**/api/v1/chat/conversations", async (route, request) => {
      if (request.method() === "POST") {
        createConversationCalls += 1;
      }
      await route.fallback();
    });

    await page.route(
      `**/api/v1/chat/conversations?project_id=${handle.seedProjectId}`,
      async (route) => {
        await new Promise((resolve) => setTimeout(resolve, 150));
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              id: "conv-existing",
              project_id: handle.seedProjectId,
              title: "保留的历史会话",
              updated_at: "2026-03-17T08:00:00.000Z",
            },
          ]),
        });
      },
    );

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await expect(
      page.locator(".chat-sidebar-item-title").first(),
    ).toContainText("保留的历史会话");
    expect(createConversationCalls).toBe(0);
  });

  test("chat mode switching does not create a new conversation", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });
    let createConversationCalls = 0;

    await page.route("**/api/v1/chat/conversations", async (route, request) => {
      if (request.method() === "POST") {
        createConversationCalls += 1;
      }
      await route.fallback();
    });

    await page.route(
      `**/api/v1/chat/conversations?project_id=${handle.seedProjectId}`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              id: "conv-existing-mode",
              project_id: handle.seedProjectId,
              title: "已有会话",
              updated_at: "2026-03-17T08:00:00.000Z",
            },
          ]),
        });
      },
    );

    await page.route(
      "**/api/v1/chat/conversations/conv-existing-mode/messages",
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        });
      },
    );

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await expect(
      page.locator(".chat-sidebar-item-title").first(),
    ).toContainText("已有会话");
    const modeSwitcher = page.locator(".chat-mode-switcher").first();

    await modeSwitcher.getByRole("button", { name: /实时语音/ }).click();
    await expect(
      modeSwitcher.locator(".chat-mode-chip.is-active"),
    ).toContainText("实时语音");

    await modeSwitcher.getByRole("button", { name: /合成实时/ }).click();
    await expect(
      modeSwitcher.locator(".chat-mode-chip.is-active"),
    ).toContainText("合成实时");

    await modeSwitcher.getByRole("button", { name: /普通对话/ }).click();
    await expect(
      modeSwitcher.locator(".chat-mode-chip.is-active"),
    ).toContainText("普通对话");
    expect(createConversationCalls).toBe(0);
  });

  test("memory graph controls stay visible after zooming out", async ({
    page,
  }) => {
    test.slow();
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/memory?project_id=${handle.seedProjectId}`);
    await page.getByRole("button", { name: "缩小" }).click();

    await expect(page.locator(".graph-controls")).toBeVisible();
    await expect(page.locator(".graph-controls-stats").first()).toBeVisible();
    await expect(page.locator(".graph-controls-btn.is-add")).toBeVisible();
  });

  test("memory orbit mode shows 3D interaction guidance", async ({ page }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/memory?project_id=${handle.seedProjectId}`);
    await page.getByRole("button", { name: "3D 探索" }).click();

    await expect(
      page.locator(".graph-controls-mode-badge.is-orbit"),
    ).toContainText("3D 探索");
    await expect(page.locator(".graph-controls-mode-hint")).toContainText(
      "拖拽旋转",
    );
  });

  test("personality card shows a friendly placeholder when empty", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.route(
      `**/api/v1/projects/${handle.seedProjectId}`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: handle.seedProjectId,
            name: "Seed Console Project",
            description: "",
            created_at: "2026-03-14T12:00:00.000Z",
          }),
        });
      },
    );

    await page.goto(`/app/assistants/${handle.seedProjectId}`);
    const personalityCard = page.locator(".profile-card").first();

    await expect(personalityCard).toContainText("暂未设定");
    await expect(personalityCard).not.toContainText("---");
  });

  test("session expiry shows a toast and redirects back to login", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.route(
      `**/api/v1/chat/conversations?project_id=${handle.seedProjectId}`,
      async (route) => {
        await route.fulfill({
          status: 401,
          contentType: "application/json",
          body: JSON.stringify({
            error: {
              code: "unauthorized",
              message: "Unauthorized",
            },
          }),
        });
      },
    );

    await page.goto("/app/chat");
    await expect(
      page.locator("[role='status']").filter({ hasText: "登录已过期" }),
    ).toBeVisible();
    await expect(page).toHaveURL(/\/login\?next=%2Fapp%2Fchat/);
  });
});
