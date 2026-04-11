import { expect, test } from "@playwright/test";
import { installWorkbenchApiMock } from "./helpers/mockWorkbenchApi";

test.use({ locale: "zh-CN" });

test.describe("Realtime Voice", () => {
  test("allows microphone use and syncs completed turns into chat", async ({ page }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.addInitScript(() => {
      class FakeTrack {
        stop(): void {}
      }

      class FakeMediaStream {
        getTracks(): FakeTrack[] {
          return [new FakeTrack()];
        }
      }

      class FakeAudioNode {
        connect(): void {}
        disconnect(): void {}
      }

      class FakeGainNode extends FakeAudioNode {
        gain = { value: 1 };
      }

      class FakeScriptProcessorNode extends FakeAudioNode {
        onaudioprocess: ((event: unknown) => void) | null = null;
      }

      class FakeBufferSource extends FakeAudioNode {
        buffer: { duration: number } | null = null;

        start(): void {}
      }

      class FakeAudioContext {
        currentTime = 0;
        destination = {};

        constructor() {}

        createMediaStreamSource(): FakeAudioNode {
          return new FakeAudioNode();
        }

        createScriptProcessor(): FakeScriptProcessorNode {
          return new FakeScriptProcessorNode();
        }

        createGain(): FakeGainNode {
          return new FakeGainNode();
        }

        createBuffer(_channels: number, length: number, sampleRate: number) {
          void sampleRate;
          return {
            duration: 0.1,
            getChannelData(): Float32Array {
              return new Float32Array(length);
            },
          };
        }

        createBufferSource(): FakeBufferSource {
          return new FakeBufferSource();
        }

        close(): Promise<void> {
          return Promise.resolve();
        }
      }

      class FakeWebSocket {
        static CONNECTING = 0;
        static OPEN = 1;
        static CLOSING = 2;
        static CLOSED = 3;

        binaryType = "arraybuffer";
        readyState = FakeWebSocket.CONNECTING;
        onopen: ((event: Event) => void) | null = null;
        onmessage: ((event: MessageEvent) => void) | null = null;
        onclose: ((event: CloseEvent) => void) | null = null;
        onerror: ((event: Event) => void) | null = null;

        constructor(url: string | URL) {
          (window as Window & { __lastRealtimeWsUrl?: string }).__lastRealtimeWsUrl = String(url);
          window.setTimeout(() => {
            this.readyState = FakeWebSocket.OPEN;
            this.onopen?.(new Event("open"));
          }, 0);
        }

        send(data: string | ArrayBufferLike | Blob | ArrayBufferView): void {
          if (typeof data !== "string") {
            return;
          }

          const message = JSON.parse(data) as { type?: string };
          if (message.type === "session.start") {
            const emit = (payload: unknown, delay: number) => {
              window.setTimeout(() => {
                this.onmessage?.(
                  new MessageEvent("message", {
                    data: JSON.stringify(payload),
                  }),
                );
              }, delay);
            };

            emit({ type: "session.ready" }, 10);
            emit({ type: "transcript.final", text: "你好" }, 20);
            emit({ type: "response.text", text: "你好，我在。" }, 30);
            emit({ type: "response.done" }, 40);
            return;
          }

          if (message.type === "session.end") {
            this.close();
          }
        }

        close(): void {
          if (this.readyState === FakeWebSocket.CLOSED) {
            return;
          }
          this.readyState = FakeWebSocket.CLOSED;
          window.setTimeout(() => {
            this.onclose?.(new CloseEvent("close"));
          }, 0);
        }
      }

      Object.defineProperty(window, "WebSocket", {
        configurable: true,
        writable: true,
        value: FakeWebSocket,
      });

      Object.defineProperty(window, "AudioContext", {
        configurable: true,
        writable: true,
        value: FakeAudioContext,
      });

      Object.defineProperty(navigator, "mediaDevices", {
        configurable: true,
        value: {
          getUserMedia: async () => new FakeMediaStream(),
        },
      });
    });

    const response = await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    expect(response).not.toBeNull();
    expect(response?.headers()["permissions-policy"] || "").toContain("microphone=(self)");
    expect(response?.headers()["permissions-policy"] || "").toContain("camera=(self)");

    await page.locator(".chat-sidebar-new").click();
    await page.locator(".chat-workspace-controls .chat-mode-dropdown").first().selectOption("omni_realtime");
    await expect(page.locator(".rt-entry")).toBeVisible();

    await page.locator(".rt-entry").click();

    await expect(page.locator(".chat-message.is-user").last()).toContainText("你好");
    await expect(page.locator(".chat-message.is-assistant").last()).toContainText("你好，我在。");

    const wsUrl = await page.evaluate(
      () => (window as Window & { __lastRealtimeWsUrl?: string }).__lastRealtimeWsUrl || "",
    );
    expect(wsUrl).toContain("/api/v1/realtime/voice");
    expect(new URL(wsUrl).search).toBe("");
  });
});
