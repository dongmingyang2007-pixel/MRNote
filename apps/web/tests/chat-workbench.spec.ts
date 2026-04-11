import { expect, test, type Page } from "@playwright/test";

import { installWorkbenchApiMock } from "./helpers/mockWorkbenchApi";

async function stubBrowserVoiceApis(page: Page) {
  await page.addInitScript(() => {
    class MockAudio {
      currentTime = 0;
      onended: (() => void) | null = null;
      onerror: (() => void) | null = null;
      play() {
        queueMicrotask(() => this.onended?.());
        return Promise.resolve();
      }
      pause() {
        return undefined;
      }
    }

    Object.defineProperty(window, "Audio", {
      configurable: true,
      writable: true,
      value: MockAudio,
    });
  });
}

test.describe("Chat Workbench", () => {
  test("thinking renders inline while sources collapse into a compact entry", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, {
      authenticated: true,
      seedConversations: [
        {
          id: "conv-workbench-thinking",
          title: "工作台测试",
        },
      ],
    });

    await page.route(
      "**/api/v1/chat/conversations/*/messages",
      async (route, request) => {
        if (request.method() !== "POST") {
          await route.fallback();
          return;
        }

        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "msg-workbench-thinking",
            conversation_id: "conv-workbench-thinking",
            role: "assistant",
            content: "这是最终回答。[ref_1]",
            reasoning_content: "这是原始思路内容。",
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
            },
            created_at: "2026-03-14T12:00:00.000Z",
          }),
        });
      },
    );

    await page.goto(
      `/app/chat?project_id=${handle.seedProjectId}&conv=conv-workbench-thinking`,
    );
    await page.getByRole("textbox", { name: "输入消息…" }).fill("给我一个总结");
    await page.getByRole("button", { name: "发送" }).click();

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    await expect(
      assistantMessage.locator(".chat-source-summary-trigger"),
    ).toContainText("来源");
    await expect(assistantMessage.locator(".chat-meta-chip--thinking")).toHaveCount(0);
    await expect(assistantMessage.locator(".chat-thinking-inline")).toContainText(
      "思考步骤",
    );
    expect(
      await assistantMessage.evaluate((node) => {
        const thinking = node.querySelector(".chat-thinking-inline");
        const bubble = node.querySelector(".chat-bubble");
        if (!thinking || !bubble) {
          return false;
        }
        return Boolean(
          thinking.compareDocumentPosition(bubble) &
            Node.DOCUMENT_POSITION_FOLLOWING,
        );
      }),
    ).toBe(true);
    await assistantMessage.locator(".chat-source-summary-trigger").click();
    await expect(page.locator(".chat-inspector-panel")).toContainText(
      "Aliyun Docs",
    );
    await assistantMessage.locator(".chat-thinking-inline-toggle").click();
    await expect(assistantMessage.locator(".chat-thinking-inline-body")).toContainText(
      "这是原始思路内容。",
    );
  });

  test("memory write inspector fetches details lazily and reflects edit, promote, and delete immediately", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, {
      authenticated: true,
      seedConversations: [
        {
          id: "conv-workbench-memory",
          title: "工作台测试",
        },
      ],
    });
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

        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "msg-workbench-memory",
            conversation_id: "conv-workbench-memory",
            role: "assistant",
            content: "这轮会写入一条记忆。",
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
        await route.fulfill({ status: 204, body: "" });
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

    await page.goto(
      `/app/chat?project_id=${handle.seedProjectId}&conv=conv-workbench-memory`,
    );
    await page.getByRole("textbox", { name: "输入消息…" }).fill("记一下");
    await page.getByRole("button", { name: "发送" }).click();

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    const memoryCard = assistantMessage.locator(".chat-memory-summary-card");
    await expect(memoryCard).toContainText("记住了");
    await expect(memoryCard).toContainText("新增临时记忆 1 条");
    await expect(memoryCard).toContainText("用户准备继续学习微分几何。");
    await assistantMessage.locator(".chat-memory-summary-open").click();

    const inspector = page.locator(".chat-inspector-panel");
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

    await inspector.getByRole("button", { name: "升为长期" }).click();
    await expect(inspector).toContainText("长期档案");

    await inspector.getByRole("button", { name: "删除" }).click();
    await expect(inspector).toContainText("这轮没有写入记忆");
    await expect(memoryCard).toHaveCount(0);
  });

  test("mobile context inspector opens as a bottom sheet", async ({ page }) => {
    const handle = await installWorkbenchApiMock(page, {
      authenticated: true,
      seedConversations: [
        {
          id: "conv-workbench-mobile",
          title: "工作台测试",
        },
      ],
    });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.route(
      "**/api/v1/chat/conversations/*/messages",
      async (route, request) => {
        if (request.method() !== "POST") {
          await route.fallback();
          return;
        }

        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "msg-workbench-mobile",
            conversation_id: "conv-workbench-mobile",
            role: "assistant",
            content: "这里有上下文材料。",
            reasoning_content: null,
            metadata_json: {
              retrieval_trace: {
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
              },
            },
            created_at: "2026-03-14T12:00:00.000Z",
          }),
        });
      },
    );

    await page.goto(
      `/app/chat?project_id=${handle.seedProjectId}&conv=conv-workbench-mobile`,
    );
    await page.getByRole("textbox", { name: "输入消息…" }).fill("移动端看看");
    await page.getByRole("button", { name: "发送" }).click();

    await page.locator(".chat-meta-chip--context").click();
    await expect(page.locator(".chat-inspector-sheet")).toBeVisible();
    await expect(page.locator(".chat-inspector-sheet")).toContainText(
      "指南.pdf",
    );
  });

  test("tools menu toggles active rails and still sends deep-analysis requests", async ({
    page,
  }) => {
    const handle = await installWorkbenchApiMock(page, {
      authenticated: true,
      seedConversations: [
        {
          id: "conv-workbench-tools",
          title: "工作台测试",
        },
      ],
    });
    await stubBrowserVoiceApis(page);
    const bodies: Array<{ content?: string; enable_thinking?: boolean }> = [];

    await page.route(
      "**/api/v1/chat/conversations/*/messages",
      async (route, request) => {
        if (request.method() === "POST") {
          bodies.push(
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
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ audio_response: "AQID" }),
      });
    });

    await page.goto(
      `/app/chat?project_id=${handle.seedProjectId}&conv=conv-workbench-tools`,
    );
    await page.getByRole("button", { name: "工具" }).click();
    await page
      .locator(".chat-tools-menu-item", { hasText: "自动朗读" })
      .click();
    await page.getByRole("button", { name: "工具" }).click();
    await page
      .locator(".chat-tools-menu-item", { hasText: "深入分析" })
      .click();

    await expect(page.locator(".chat-active-tools")).toContainText("自动朗读");
    await expect(page.locator(".chat-active-tools")).toContainText("深入分析");

    await page.getByRole("textbox", { name: "输入消息…" }).fill("帮我拆一下");
    await page.getByRole("button", { name: "发送" }).click();

    await expect.poll(() => bodies.length).toBe(1);
    expect(bodies[0]).toEqual({
      content: "帮我拆一下",
      enable_thinking: true,
    });
  });

  test("keeps the stream failure message visible after the post-abort sync refresh", async ({
    page,
  }) => {
    test.setTimeout(45_000);

    const handle = await installWorkbenchApiMock(page, {
      authenticated: true,
      seedConversations: [
        {
          id: "conv-workbench-stream-timeout",
          title: "流式超时测试",
        },
      ],
    });

    const messages: Array<{
      id: string;
      conversation_id: string;
      role: "user" | "assistant";
      content: string;
      metadata_json: Record<string, unknown>;
      created_at: string;
    }> = [
      {
        id: "msg-existing-assistant",
        conversation_id: "conv-workbench-stream-timeout",
        role: "assistant" as const,
        content: "之前的正常回复",
        metadata_json: {},
        created_at: "2026-03-14T12:00:00.000Z",
      },
    ];

    await page.route(
      "**/api/v1/chat/conversations/conv-workbench-stream-timeout/messages",
      async (route, request) => {
        if (request.method() === "GET") {
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(messages),
          });
          return;
        }

        await route.fallback();
      },
    );

    await page.route(
      "**/api/v1/chat/conversations/conv-workbench-stream-timeout/stream",
      async (route, request) => {
        if (request.method() !== "POST") {
          await route.fallback();
          return;
        }

        const body = request.postDataJSON() as { content?: string };
        messages.push({
          id: "msg-timeout-user",
          conversation_id: "conv-workbench-stream-timeout",
          role: "user",
          content: body.content || "",
          metadata_json: {},
          created_at: "2026-03-14T12:00:01.000Z",
        });

        await new Promise((resolve) => setTimeout(resolve, 16_000));
        try {
          await route.fulfill({
            status: 200,
            contentType: "text/event-stream",
            body: "",
          });
        } catch {
          // The browser aborts this request after the client-side watchdog fires.
        }
      },
    );

    await page.goto(
      `/app/chat?project_id=${handle.seedProjectId}&conv=conv-workbench-stream-timeout`,
    );
    await page.getByRole("textbox", { name: "输入消息…" }).fill("为什么没有回复");
    await page.getByRole("button", { name: "发送" }).click();

    const assistantMessage = page.locator(".chat-message.is-assistant").last();
    await expect(assistantMessage).toContainText("流式响应时发生错误。", {
      timeout: 25_000,
    });
  });
});
