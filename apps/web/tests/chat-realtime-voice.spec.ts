import { expect, test, type Page } from "@playwright/test";
import { installWorkbenchApiMock } from "./helpers/mockWorkbenchApi";

test.use({ locale: "zh-CN" });

async function switchToOmniRealtime(page: Page) {
  await page.locator(".chat-workspace-controls .chat-mode-dropdown").first().selectOption("omni_realtime");
}

async function switchToSyntheticRealtime(page: Page) {
  await page.locator(".chat-workspace-controls .chat-mode-dropdown").first().selectOption("synthetic_realtime");
}

async function forceSelectRealtimeProject(page: Page, projectId: string) {
  await page.evaluate(({ nextProjectId }) => {
    const select = document.querySelector<HTMLSelectElement>(".inline-topbar-project-select");
    if (!select) {
      return;
    }
    if (!Array.from(select.options).some((option) => option.value === nextProjectId)) {
      const option = document.createElement("option");
      option.value = nextProjectId;
      option.textContent = nextProjectId;
      select.appendChild(option);
    }
  }, { nextProjectId: projectId });
  await page.locator(".inline-topbar-project-select").selectOption(projectId);
}

async function ensureRealtimeConversationReady(page: Page, projectId: string) {
  const activeConversation = page.locator(".chat-sidebar-item.is-active");
  try {
    await expect(activeConversation).toBeVisible({ timeout: 8000 });
    return;
  } catch {
    await forceSelectRealtimeProject(page, projectId);
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

async function installRealtimeVoiceMocks(
  page: Page,
  scenario:
    | "success"
    | "permission-denied"
    | "turn-error"
    | "partial-first"
    | "omni-pending-interrupt"
    | "omni-camera"
    | "synthetic-camera"
    | "synthetic-cumulative-user"
    | "synthetic-echo"
    | "synthetic-pending-no-interrupt"
    | "synthetic-autoplay",
) {
  await page.evaluate(
    ({ activeScenario }) => {
      const mockProcessors: MockScriptProcessor[] = [];
      const sentPayloadTypes: string[] = [];
      const sentImagePayloads: string[] = [];
      const sentMediaPayloads: string[] = [];
      Object.defineProperty(window, "__mockRealtimeSentTypes", {
        configurable: true,
        value: sentPayloadTypes,
      });
      Object.defineProperty(globalThis, "__mockRealtimeSentTypes", {
        configurable: true,
        value: sentPayloadTypes,
      });
      Object.defineProperty(window, "__mockRealtimeImagePayloads", {
        configurable: true,
        value: sentImagePayloads,
      });
      Object.defineProperty(globalThis, "__mockRealtimeImagePayloads", {
        configurable: true,
        value: sentImagePayloads,
      });
      Object.defineProperty(window, "__mockRealtimeMediaPayloads", {
        configurable: true,
        value: sentMediaPayloads,
      });
      Object.defineProperty(globalThis, "__mockRealtimeMediaPayloads", {
        configurable: true,
        value: sentMediaPayloads,
      });

      const emitSpeechFrame = (amplitude = 0.25) => {
        const frame = new Float32Array(4096).fill(amplitude);
        for (const processor of mockProcessors) {
          processor.onaudioprocess?.({
            inputBuffer: {
              getChannelData: () => frame,
            },
          });
        }
      };

      class MockAudioBuffer {
        duration: number;
        channelData: Float32Array;

        constructor(length: number, sampleRate: number) {
          this.duration = length / sampleRate;
          this.channelData = new Float32Array(length);
        }

        getChannelData() {
          return this.channelData;
        }
      }

      class MockBufferSource {
        buffer: MockAudioBuffer | null = null;

        connect() {
          return undefined;
        }

        start() {
          return undefined;
        }
      }

      class MockMediaStreamSource {
        connect() {
          return undefined;
        }
      }

      class MockScriptProcessor {
        onaudioprocess: ((event: { inputBuffer: { getChannelData: () => Float32Array } }) => void) | null = null;

        constructor() {
          mockProcessors.push(this);
        }

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
        static readonly sampleRate = 24000;
        state: "running" | "suspended" | "closed" = "running";
        currentTime = 0;
        destination = {};

        constructor() {}

        resume() {
          this.state = "running";
          return Promise.resolve();
        }

        close() {
          this.state = "closed";
          return Promise.resolve();
        }

        createBuffer(_channels: number, length: number, sampleRate: number) {
          return new MockAudioBuffer(length, sampleRate);
        }

        createBufferSource() {
          return new MockBufferSource();
        }

        createMediaStreamSource() {
          return new MockMediaStreamSource();
        }

        createScriptProcessor() {
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

      Object.defineProperty(window.navigator, "mediaDevices", {
        configurable: true,
        value: {
          enumerateDevices: () =>
            Promise.resolve([
              {
                kind: "videoinput",
                deviceId: "front-camera",
                label: "前置镜头",
              },
              {
                kind: "videoinput",
                deviceId: "rear-camera",
                label: "后置镜头",
              },
            ]),
          addEventListener: () => undefined,
          removeEventListener: () => undefined,
          getUserMedia: (constraints?: { video?: unknown }) => {
            if (activeScenario === "permission-denied") {
              return Promise.reject(new Error("permission denied"));
            }
            const isVideoRequest = Boolean(constraints && typeof constraints === "object" && "video" in constraints);
            const requestedDeviceId =
              isVideoRequest &&
              constraints &&
              typeof constraints === "object" &&
              constraints.video &&
              typeof constraints.video === "object" &&
              "deviceId" in constraints.video &&
              constraints.video.deviceId &&
              typeof constraints.video.deviceId === "object" &&
              "exact" in constraints.video.deviceId
                ? String(constraints.video.deviceId.exact)
                : "front-camera";

            return Promise.resolve({
              getTracks: () => [
                {
                  kind: isVideoRequest ? "video" : "audio",
                  stop() {},
                  getSettings: () =>
                    isVideoRequest ? { deviceId: requestedDeviceId } : {},
                },
              ],
              getVideoTracks: () =>
                isVideoRequest
                  ? [
                      {
                        kind: "video",
                        stop() {},
                        getSettings: () => ({ deviceId: requestedDeviceId }),
                      },
                    ]
                  : [],
              getAudioTracks: () =>
                isVideoRequest
                  ? []
                  : [
                      {
                        kind: "audio",
                        stop() {},
                        getSettings: () => ({}),
                      },
                    ],
            });
          },
        },
      });

      if (activeScenario === "omni-camera" || activeScenario === "synthetic-camera") {
        Object.defineProperty(HTMLMediaElement.prototype, "srcObject", {
          configurable: true,
          get() {
            return (this as HTMLMediaElement & { __mockSrcObject?: unknown }).__mockSrcObject ?? null;
          },
          set(value: unknown) {
            (this as HTMLMediaElement & { __mockSrcObject?: unknown }).__mockSrcObject = value;
          },
        });
        Object.defineProperty(HTMLVideoElement.prototype, "videoWidth", {
          configurable: true,
          get() {
            return 1280;
          },
        });
        Object.defineProperty(HTMLVideoElement.prototype, "videoHeight", {
          configurable: true,
          get() {
            return 720;
          },
        });
        Object.defineProperty(HTMLMediaElement.prototype, "play", {
          configurable: true,
          value() {
            const media = this as HTMLMediaElement;
            setTimeout(() => {
              media.dispatchEvent(new Event("loadedmetadata"));
            }, 0);
            return Promise.resolve();
          },
        });
        Object.defineProperty(HTMLMediaElement.prototype, "pause", {
          configurable: true,
          value() {
            return undefined;
          },
        });
        Object.defineProperty(HTMLMediaElement.prototype, "load", {
          configurable: true,
          value() {
            return undefined;
          },
        });
        Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
          configurable: true,
          value() {
            return {
              drawImage() {
                return undefined;
              },
            };
          },
        });
        Object.defineProperty(HTMLCanvasElement.prototype, "toDataURL", {
          configurable: true,
          value() {
            return "data:image/jpeg;base64,/9j/2wBDAA==";
          },
        });
      }

      if (activeScenario === "synthetic-camera") {
        class MockMediaRecorder {
          static isTypeSupported(mimeType: string) {
            return mimeType.startsWith("video/webm");
          }

          readonly mimeType: string;
          state: "inactive" | "recording" = "inactive";
          ondataavailable: ((event: { data: Blob }) => void) | null = null;
          onstop: ((event: Event) => void) | null = null;
          private timer: number | null = null;

          constructor(_stream: MediaStream, options?: { mimeType?: string }) {
            this.mimeType = options?.mimeType || "video/webm";
          }

          private emitChunk() {
            this.ondataavailable?.({
              data: new Blob(["mock-video-chunk"], { type: this.mimeType }),
            });
          }

          start(timeslice?: number) {
            this.state = "recording";
            const intervalMs = Math.max(Number(timeslice) || 1000, 50);
            this.timer = window.setInterval(() => {
              this.emitChunk();
            }, intervalMs);
          }

          stop() {
            if (this.state === "inactive") {
              return;
            }
            this.state = "inactive";
            if (this.timer !== null) {
              window.clearInterval(this.timer);
              this.timer = null;
            }
            this.emitChunk();
            setTimeout(() => {
              this.onstop?.(new Event("stop"));
            }, 0);
          }
        }

        Object.defineProperty(window, "MediaRecorder", {
          configurable: true,
          writable: true,
          value: MockMediaRecorder,
        });
        Object.defineProperty(globalThis, "MediaRecorder", {
          configurable: true,
          writable: true,
          value: MockMediaRecorder,
        });
      }

      if (activeScenario === "synthetic-autoplay") {
        const mockAudioStats = {
          primed: 0,
          replyPlays: 0,
        };
        let unlocked = false;
        Object.defineProperty(window, "__mockAudioStats", {
          configurable: true,
          value: mockAudioStats,
        });
        Object.defineProperty(globalThis, "__mockAudioStats", {
          configurable: true,
          value: mockAudioStats,
        });
        Object.defineProperty(HTMLMediaElement.prototype, "play", {
          configurable: true,
          value() {
            const media = this as HTMLMediaElement;
            const src = media.currentSrc || media.src || "";
            if (src.startsWith("data:audio/wav;base64,")) {
              unlocked = true;
              mockAudioStats.primed += 1;
              return Promise.resolve();
            }
            if (!unlocked) {
              return Promise.reject(new DOMException("autoplay blocked", "NotAllowedError"));
            }
            mockAudioStats.replyPlays += 1;
            setTimeout(() => {
              media.onended?.(new Event("ended"));
            }, 0);
            return Promise.resolve();
          },
        });
        Object.defineProperty(HTMLMediaElement.prototype, "pause", {
          configurable: true,
          value() {
            return undefined;
          },
        });
        Object.defineProperty(HTMLMediaElement.prototype, "load", {
          configurable: true,
          value() {
            return undefined;
          },
        });
      }

      class MockWebSocket {
        static readonly CONNECTING = 0;
        static readonly OPEN = 1;
        static readonly CLOSING = 2;
        static readonly CLOSED = 3;

        readonly url: string;
        readyState = MockWebSocket.CONNECTING;
        binaryType = "blob";
        onopen: ((event: unknown) => void) | null = null;
        onmessage: ((event: { data: string | ArrayBuffer | Blob }) => void) | null = null;
        onclose: ((event: { code: number; reason: string }) => void) | null = null;
        onerror: ((event: unknown) => void) | null = null;
        assistantTurnOpen = false;
        interrupted = false;
        syntheticCameraResponded = false;

        constructor(url: string) {
          this.url = url;
          setTimeout(() => {
            this.readyState = MockWebSocket.OPEN;
            this.onopen?.({});
          }, 0);
        }

        send(data: string | ArrayBuffer) {
          if (typeof data !== "string") {
            sentPayloadTypes.push("binary");
            if (
              activeScenario === "synthetic-echo" &&
              this.url.includes("/api/v1/realtime/composed-voice") &&
              this.assistantTurnOpen
            ) {
              this.interrupted = true;
              this.assistantTurnOpen = false;
              setTimeout(() => {
                this.onmessage?.({ data: JSON.stringify({ type: "interrupt.ack" }) });
              }, 0);
            }
            return;
          }

          const payload = JSON.parse(data);
          if (typeof payload.type === "string") {
            sentPayloadTypes.push(payload.type);
          }
          if (payload.type === "input.image.append" && typeof payload.data_url === "string") {
            sentImagePayloads.push(payload.data_url);
          }
          if (payload.type === "media.set" && typeof payload.data_url === "string") {
            sentMediaPayloads.push(payload.data_url);
          }
          if (payload.type === "media.frame.append" && typeof payload.data_url === "string") {
            sentMediaPayloads.push(payload.data_url);
          }
          if (payload.type === "session.start") {
            setTimeout(() => {
              this.onmessage?.({ data: JSON.stringify({ type: "session.ready" }) });
            }, 0);

            if (activeScenario === "success") {
              setTimeout(() => {
                this.onmessage?.({
                  data: JSON.stringify({ type: "transcript.final", text: "语音问题" }),
                });
              }, 30);
              setTimeout(() => {
                this.onmessage?.({
                  data: JSON.stringify({ type: "response.text", text: "语音回答" }),
                });
              }, 60);
              setTimeout(() => {
                this.onmessage?.({
                  data: JSON.stringify({ type: "response.done" }),
                });
              }, 90);
            } else if (activeScenario === "turn-error") {
              setTimeout(() => {
                this.onmessage?.({
                  data: JSON.stringify({ type: "transcript.final", text: "语音问题" }),
                });
              }, 30);
              setTimeout(() => {
                this.onmessage?.({
                  data: JSON.stringify({ type: "response.text", text: "回答到一半" }),
                });
              }, 60);
              setTimeout(() => {
                this.onmessage?.({
                  data: JSON.stringify({ type: "turn.error", message: "AI 暂时无响应，请重试" }),
                });
              }, 90);
            } else if (activeScenario === "partial-first") {
              setTimeout(() => {
                this.onmessage?.({
                  data: JSON.stringify({ type: "transcript.partial", text: "语" }),
                });
              }, 20);
              setTimeout(() => {
                this.onmessage?.({
                  data: JSON.stringify({ type: "transcript.partial", text: "语音" }),
                });
              }, 80);
              setTimeout(() => {
                this.onmessage?.({
                  data: JSON.stringify({ type: "transcript.final", text: "语音问题" }),
                });
              }, 160);
            } else if (activeScenario === "omni-pending-interrupt" && this.url.includes("/api/v1/realtime/voice")) {
              setTimeout(() => {
                this.onmessage?.({
                  data: JSON.stringify({ type: "transcript.final", text: "第一句" }),
                });
              }, 30);
              setTimeout(() => emitSpeechFrame(), 120);
              setTimeout(() => emitSpeechFrame(), 260);
              setTimeout(() => emitSpeechFrame(), 430);
              setTimeout(() => emitSpeechFrame(), 610);
              setTimeout(() => emitSpeechFrame(), 780);
              setTimeout(() => {
                if (!this.interrupted) {
                  this.assistantTurnOpen = true;
                  this.onmessage?.({
                    data: JSON.stringify({ type: "response.text", text: "第一句回复" }),
                  });
                }
              }, 900);
              setTimeout(() => {
                if (this.interrupted) {
                  this.onmessage?.({
                    data: JSON.stringify({ type: "response.text", text: "旧轮残留" }),
                  });
                }
              }, 930);
              setTimeout(() => {
                if (!this.interrupted) {
                  this.assistantTurnOpen = false;
                  this.onmessage?.({
                    data: JSON.stringify({ type: "response.done" }),
                  });
                }
              }, 980);
              setTimeout(() => {
                if (this.interrupted) {
                  this.onmessage?.({
                    data: JSON.stringify({ type: "response.done" }),
                  });
                }
              }, 990);
              setTimeout(() => {
                this.interrupted = false;
                this.onmessage?.({
                  data: JSON.stringify({ type: "transcript.final", text: "第二句" }),
                });
              }, 1040);
              setTimeout(() => {
                this.assistantTurnOpen = true;
                this.onmessage?.({
                  data: JSON.stringify({ type: "response.text", text: "第二句回复" }),
                });
              }, 1100);
              setTimeout(() => {
                this.assistantTurnOpen = false;
                this.onmessage?.({
                  data: JSON.stringify({ type: "response.done" }),
                });
              }, 1160);
            } else if (activeScenario === "omni-camera" && this.url.includes("/api/v1/realtime/voice")) {
              setTimeout(() => {
                this.onmessage?.({
                  data: JSON.stringify({ type: "transcript.partial", text: "正在连接视觉流" }),
                });
              }, 40);
            } else if (activeScenario === "synthetic-camera" && this.url.includes("/api/v1/realtime/composed-voice")) {
              setTimeout(() => emitSpeechFrame(), 40);
              setTimeout(() => emitSpeechFrame(), 90);
              setTimeout(() => emitSpeechFrame(), 140);
              setTimeout(() => emitSpeechFrame(0), 1100);
              setTimeout(() => emitSpeechFrame(0), 1500);
            } else if (activeScenario === "synthetic-pending-no-interrupt" && this.url.includes("/api/v1/realtime/composed-voice")) {
              setTimeout(() => {
                this.onmessage?.({
                  data: JSON.stringify({ type: "transcript.final", text: "第一句还没说完" }),
                });
              }, 30);
              setTimeout(() => emitSpeechFrame(), 100);
              setTimeout(() => emitSpeechFrame(), 260);
              setTimeout(() => emitSpeechFrame(), 430);
              setTimeout(() => emitSpeechFrame(), 610);
              setTimeout(() => emitSpeechFrame(), 780);
              setTimeout(() => {
                this.assistantTurnOpen = true;
                this.onmessage?.({
                  data: JSON.stringify({ type: "response.text", text: "等你说完后我再回答。" }),
                });
              }, 900);
              setTimeout(() => {
                this.assistantTurnOpen = false;
                this.onmessage?.({
                  data: JSON.stringify({ type: "response.done" }),
                });
              }, 980);
            } else if (activeScenario === "synthetic-echo" && this.url.includes("/api/v1/realtime/composed-voice")) {
              setTimeout(() => {
                this.onmessage?.({
                  data: JSON.stringify({ type: "transcript.final", text: "第一句" }),
                });
              }, 30);
              setTimeout(() => {
                this.assistantTurnOpen = true;
                this.onmessage?.({
                  data: JSON.stringify({ type: "response.text", text: "第一句回复" }),
                });
              }, 70);
              setTimeout(() => {
                this.onmessage?.({
                  data: JSON.stringify({ type: "audio.meta", mime: "audio/mpeg" }),
                });
              }, 80);
              setTimeout(() => {
                this.onmessage?.({
                  data: new Blob(["mock-audio-1"], { type: "audio/mpeg" }),
                });
              }, 90);
              setTimeout(() => {
                emitSpeechFrame();
              }, 100);
              setTimeout(() => {
                if (this.interrupted) {
                  this.onmessage?.({
                    data: JSON.stringify({ type: "response.text", text: "旧轮残留" }),
                  });
                }
              }, 110);
              setTimeout(() => {
                if (!this.interrupted) {
                  this.assistantTurnOpen = false;
                  this.onmessage?.({
                    data: JSON.stringify({ type: "response.done" }),
                  });
                }
              }, 130);
              setTimeout(() => {
                if (this.interrupted) {
                  this.onmessage?.({
                    data: JSON.stringify({ type: "response.done" }),
                  });
                }
              }, 145);
              setTimeout(() => {
                this.interrupted = false;
                this.onmessage?.({
                  data: JSON.stringify({ type: "transcript.final", text: "第二句" }),
                });
              }, 190);
              setTimeout(() => {
                this.assistantTurnOpen = true;
                this.onmessage?.({
                  data: JSON.stringify({ type: "response.text", text: "第二句回复" }),
                });
              }, 230);
              setTimeout(() => {
                this.onmessage?.({
                  data: JSON.stringify({ type: "audio.meta", mime: "audio/mpeg" }),
                });
              }, 240);
              setTimeout(() => {
                this.onmessage?.({
                  data: new Blob(["mock-audio-2"], { type: "audio/mpeg" }),
                });
              }, 250);
              setTimeout(() => {
                if (!this.interrupted) {
                  this.assistantTurnOpen = false;
                  this.onmessage?.({
                    data: JSON.stringify({ type: "response.done" }),
                  });
                }
              }, 290);
            } else if (activeScenario === "synthetic-cumulative-user" && this.url.includes("/api/v1/realtime/composed-voice")) {
              setTimeout(() => {
                this.onmessage?.({
                  data: JSON.stringify({ type: "transcript.final", text: "先做个自我介绍吧。" }),
                });
              }, 30);
              setTimeout(() => {
                this.onmessage?.({
                  data: JSON.stringify({
                    type: "transcript.final",
                    text: "先做个自我介绍吧。我是我，叫做董明阳。",
                  }),
                });
              }, 90);
              setTimeout(() => {
                this.onmessage?.({
                  data: JSON.stringify({
                    type: "transcript.final",
                    text: "先做个自我介绍吧。我是我，叫做董明阳。我来自于北京。",
                  }),
                });
              }, 150);
              setTimeout(() => {
                this.onmessage?.({
                  data: JSON.stringify({ type: "response.text", text: "你好，我是 AI 助手。" }),
                });
              }, 220);
              setTimeout(() => {
                this.onmessage?.({
                  data: JSON.stringify({ type: "response.done" }),
                });
              }, 260);
            } else if (activeScenario === "synthetic-autoplay" && this.url.includes("/api/v1/realtime/composed-voice")) {
              setTimeout(() => {
                this.onmessage?.({
                  data: JSON.stringify({ type: "transcript.final", text: "帮我播报结果" }),
                });
              }, 30);
              setTimeout(() => {
                this.onmessage?.({
                  data: JSON.stringify({ type: "response.text", text: "这是自动播报的回复。" }),
                });
              }, 70);
              setTimeout(() => {
                this.onmessage?.({
                  data: JSON.stringify({ type: "audio.meta", mime: "audio/mpeg" }),
                });
              }, 90);
              setTimeout(() => {
                this.onmessage?.({
                  data: new Blob(["mock-audio-autoplay"], { type: "audio/mpeg" }),
                });
              }, 110);
              setTimeout(() => {
                this.onmessage?.({
                  data: JSON.stringify({ type: "response.done" }),
                });
              }, 150);
            }
            return;
          }

          if (payload.type === "session.end") {
            this.close(1000, "client_end");
            return;
          }

          if (
            payload.type === "media.frame.append" &&
            activeScenario === "synthetic-camera" &&
            !this.syntheticCameraResponded
          ) {
            this.syntheticCameraResponded = true;
            setTimeout(() => {
              this.onmessage?.({
                data: JSON.stringify({ type: "transcript.final", text: "请看一下我面前的画面" }),
              });
            }, 10);
            setTimeout(() => {
              this.onmessage?.({
                data: JSON.stringify({ type: "response.text", text: "我已经结合这段画面开始理解了。" }),
              });
            }, 45);
            setTimeout(() => {
              this.onmessage?.({
                data: JSON.stringify({ type: "audio.meta", mime: "audio/mpeg" }),
              });
            }, 55);
            setTimeout(() => {
              this.onmessage?.({
                data: new Blob(["mock-audio-camera"], { type: "audio/mpeg" }),
              });
            }, 65);
            setTimeout(() => {
              this.onmessage?.({
                data: JSON.stringify({ type: "response.done" }),
              });
            }, 90);
            return;
          }

          if (payload.type === "input.interrupt" && activeScenario === "omni-pending-interrupt") {
            if (this.interrupted) {
              return;
            }
            this.interrupted = true;
            this.assistantTurnOpen = false;
            setTimeout(() => {
              this.onmessage?.({ data: JSON.stringify({ type: "interrupt.ack" }) });
            }, 0);
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
    },
    { activeScenario: scenario },
  );
}

test.describe("Realtime Voice", () => {
  test("microphone denial returns the widget to retry state", async ({ page }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await installRealtimeVoiceMocks(page, "permission-denied");
    await ensureRealtimeConversationReady(page, handle.seedProjectId);
    await switchToOmniRealtime(page);
    await expect(page.locator(".rt-entry")).toBeVisible();

    await page.locator(".rt-entry").click();

    await expect(page.locator(".rt-entry-label")).toHaveText("重试对话");
  });

  test("completed realtime turns sync into the chat pane and sidebar immediately", async ({ page }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await installRealtimeVoiceMocks(page, "success");
    await ensureRealtimeConversationReady(page, handle.seedProjectId);
    await switchToOmniRealtime(page);
    await expect(page.locator(".rt-entry")).toBeVisible();

    await page.locator(".rt-entry").click();

    await expect(page.locator(".chat-message.is-user").last()).toContainText("语音问题");
    await expect(page.locator(".chat-message.is-assistant").last()).toContainText("语音回答");
    await expect(page.locator(".chat-sidebar-item.is-active")).toContainText("语音回答");
  });

  test("turn errors keep realtime session interactive instead of dropping to retry", async ({ page }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await installRealtimeVoiceMocks(page, "turn-error");
    await ensureRealtimeConversationReady(page, handle.seedProjectId);
    await switchToOmniRealtime(page);
    await expect(page.locator(".rt-entry")).toBeVisible();

    await page.locator(".rt-entry").click();

    await expect(page.locator(".chat-message.is-user").last()).toContainText("语音问题");
    await expect(page.locator(".chat-message.is-assistant").last()).toContainText("回答到一半");
    await expect(page.locator(".rt-stage-status-text")).toHaveText("聆听中");
    await expect(page.locator(".chat-voice-indicator.is-error")).toContainText("AI 暂时无响应，请重试");
    await expect(page.locator(".rt-entry-label")).toHaveCount(0);
  });

  test("partial transcripts appear in the chat pane before the final transcript lands", async ({ page }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await installRealtimeVoiceMocks(page, "partial-first");
    await ensureRealtimeConversationReady(page, handle.seedProjectId);
    await switchToOmniRealtime(page);
    await expect(page.locator(".rt-entry")).toBeVisible();

    await page.locator(".rt-entry").click();

    await expect(page.locator(".chat-message.is-user").last()).toContainText("语");
    await expect(page.locator(".chat-message.is-user").last()).toContainText("语音");
    await expect(page.locator(".chat-message.is-user").last()).toContainText("语音问题");
  });

  test("omni realtime can interrupt before the first audio/text reply fully arrives", async ({ page }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await installRealtimeVoiceMocks(page, "omni-pending-interrupt");
    await ensureRealtimeConversationReady(page, handle.seedProjectId);
    await switchToOmniRealtime(page);
    await expect(page.locator(".rt-entry")).toBeVisible();

    await page.locator(".rt-entry").click();

    await expect(page.locator(".chat-message.is-user").last()).toContainText("第二句");
    await expect(page.locator(".chat-message.is-assistant").last()).toContainText("第二句回复");

    const userTexts = await page.locator(".chat-message.is-user").allTextContents();
    const assistantTexts = await page.locator(".chat-message.is-assistant").allTextContents();
    const sentPayloadTypes = await page.evaluate(
      () => (window as { __mockRealtimeSentTypes?: string[] }).__mockRealtimeSentTypes ?? [],
    );
    expect(userTexts.join("\n")).toContain("第一句");
    expect(userTexts.join("\n")).toContain("第二句");
    expect(sentPayloadTypes).toContain("input.interrupt");
    expect(assistantTexts.join("\n")).toContain("第二句回复");
    expect(assistantTexts.join("\n")).not.toContain("第一句回复");
    expect(assistantTexts.join("\n")).not.toContain("旧轮残留");
  });

  test("omni realtime can stream continuous camera frames from the selected device", async ({ page }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await installRealtimeVoiceMocks(page, "omni-camera");
    await ensureRealtimeConversationReady(page, handle.seedProjectId);
    await switchToOmniRealtime(page);
    await expect(page.locator(".rt-entry")).toBeVisible();

    await page.locator(".rt-entry").click();

    await expect(page.locator(".rt-camera-select")).toBeVisible();
    await page.locator(".rt-camera-select").selectOption("rear-camera");
    await page.getByRole("button", { name: "开启摄像头" }).click();

    await expect
      .poll(
        () =>
          page.evaluate(
            () =>
              (window as { __mockRealtimeImagePayloads?: string[] }).__mockRealtimeImagePayloads
                ?.length ?? 0,
          ),
        { timeout: 5000 },
      )
      .toBeGreaterThan(0);

    const sentPayloadTypes = await page.evaluate(
      () => (window as { __mockRealtimeSentTypes?: string[] }).__mockRealtimeSentTypes ?? [],
    );
    const sentImagePayloads = await page.evaluate(
      () =>
        (window as { __mockRealtimeImagePayloads?: string[] }).__mockRealtimeImagePayloads ?? [],
    );

    expect(sentPayloadTypes).toContain("input.image.append");
    expect(sentImagePayloads[0]).toContain("data:image/jpeg;base64,");
    await expect(page.locator(".rt-camera-select")).toHaveValue("rear-camera");
  });

  test("synthetic realtime keeps completed turns instead of overwriting the latest utterance", async ({ page }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await installRealtimeVoiceMocks(page, "synthetic-echo");
    await ensureRealtimeConversationReady(page, handle.seedProjectId);
    await switchToSyntheticRealtime(page);
    await expect(page.locator(".rt-entry")).toBeVisible();

    await page.locator(".rt-entry").click();

    await expect(page.locator(".chat-message.is-user").last()).toContainText("第二句");
    await expect(page.locator(".chat-message.is-assistant").last()).toContainText("第二句回复");

    const userTexts = await page.locator(".chat-message.is-user").allTextContents();
    const assistantTexts = await page.locator(".chat-message.is-assistant").allTextContents();
    expect(userTexts.join("\n")).toContain("第一句");
    expect(userTexts.join("\n")).toContain("第二句");
    expect(assistantTexts.join("\n")).toContain("第一句回复");
    expect(assistantTexts.join("\n")).toContain("第二句回复");
    expect(assistantTexts.join("\n")).not.toContain("旧轮残留");
  });

  test("synthetic realtime does not interrupt a reply that is only pending", async ({ page }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await installRealtimeVoiceMocks(page, "synthetic-pending-no-interrupt");
    await ensureRealtimeConversationReady(page, handle.seedProjectId);
    await switchToSyntheticRealtime(page);
    await expect(page.locator(".rt-entry")).toBeVisible();

    await page.locator(".rt-entry").click();

    await expect(page.locator(".chat-message.is-assistant").last()).toContainText(
      "等你说完后我再回答。",
    );

    const sentPayloadTypes = await page.evaluate(
      () => (window as { __mockRealtimeSentTypes?: string[] }).__mockRealtimeSentTypes ?? [],
    );
    expect(sentPayloadTypes).not.toContain("input.interrupt");
  });

  test("synthetic realtime can capture a turn video from the selected camera", async ({ page }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await installRealtimeVoiceMocks(page, "synthetic-camera");
    await ensureRealtimeConversationReady(page, handle.seedProjectId);
    await switchToSyntheticRealtime(page);
    await expect(page.locator(".rt-entry")).toBeVisible();

    await page.getByRole("button", { name: "开启摄像头" }).click();
    await page.locator(".rt-camera-select").selectOption("rear-camera");
    await page.locator(".rt-entry").click();

    await expect
      .poll(
        () =>
          page.evaluate(
            () =>
              (window as { __mockRealtimeMediaPayloads?: string[] }).__mockRealtimeMediaPayloads
                ?.length ?? 0,
          ),
        { timeout: 6000 },
      )
      .toBeGreaterThan(0);

    await expect(page.locator(".chat-message.is-assistant").last()).toContainText(
      "我已经结合这段画面开始理解了。",
    );

    const sentPayloadTypes = await page.evaluate(
      () => (window as { __mockRealtimeSentTypes?: string[] }).__mockRealtimeSentTypes ?? [],
    );
    const sentMediaPayloads = await page.evaluate(
      () =>
        (window as { __mockRealtimeMediaPayloads?: string[] }).__mockRealtimeMediaPayloads ?? [],
    );

    expect(sentPayloadTypes).toContain("media.frame.append");
    expect(sentMediaPayloads[0]).toContain("data:image/jpeg;base64,");
    await expect(page.locator(".rt-camera-select")).toHaveValue("rear-camera");
  });

  test("synthetic realtime keeps one user bubble while cumulative transcript grows", async ({ page }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await installRealtimeVoiceMocks(page, "synthetic-cumulative-user");
    await ensureRealtimeConversationReady(page, handle.seedProjectId);
    await switchToSyntheticRealtime(page);
    await expect(page.locator(".rt-entry")).toBeVisible();

    await page.locator(".rt-entry").click();

    await expect(page.locator(".chat-message.is-user")).toHaveCount(1);
    await expect(page.locator(".chat-message.is-user").first()).toContainText(
      "先做个自我介绍吧。我是我，叫做董明阳。我来自于北京。",
    );
    await expect(page.locator(".chat-message.is-assistant").last()).toContainText(
      "你好，我是 AI 助手。",
    );
  });

  test("synthetic realtime primes playback so spoken replies autoplay", async ({ page }) => {
    const handle = await installWorkbenchApiMock(page, { authenticated: true });

    await page.goto(`/app/chat?project_id=${handle.seedProjectId}`);
    await installRealtimeVoiceMocks(page, "synthetic-autoplay");
    await ensureRealtimeConversationReady(page, handle.seedProjectId);
    await switchToSyntheticRealtime(page);
    await expect(page.locator(".rt-entry")).toBeVisible();

    await page.locator(".rt-entry").click();

    await expect(page.locator(".chat-message.is-assistant").last()).toContainText("这是自动播报的回复。");
    await expect
      .poll(() => page.evaluate(() => (window as { __mockAudioStats?: { primed: number } }).__mockAudioStats?.primed ?? 0))
      .toBe(1);
    await expect
      .poll(() => page.evaluate(() => (window as { __mockAudioStats?: { replyPlays: number } }).__mockAudioStats?.replyPlays ?? 0))
      .toBe(1);
    await expect(page.locator(".chat-voice-indicator.is-error")).toHaveCount(0);
  });
});
