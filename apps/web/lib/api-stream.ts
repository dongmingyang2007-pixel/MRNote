// apps/web/lib/api-stream.ts
import { getApiHttpBaseUrl } from "./env";
import { buildStreamPostHeaders, handleStreamUnauthorized } from "./api";

export interface StreamEvent {
  event: string;
  data: Record<string, unknown>;
}

/**
 * SSE consumer for streaming chat responses.
 * Sends a POST request with full auth (CSRF token, workspace ID, credentials)
 * and yields parsed SSE events.
 */
export async function* apiStream(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const apiHttpBaseUrl = getApiHttpBaseUrl();
  const url = `${apiHttpBaseUrl}${path}`;

  const headers = await buildStreamPostHeaders(path);

  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      credentials: "include",
      cache: "no-store",
      signal,
    });
  } catch (error) {
    throw new Error(
      `Stream request failed: unable to reach ${url}. ${error instanceof Error ? error.message : String(error)}`,
    );
  }

  if (!response.ok) {
    if (response.status === 401) {
      handleStreamUnauthorized();
    }
    const text = await response.text();
    let parsed: Record<string, unknown> = {};
    try {
      parsed = JSON.parse(text);
    } catch {
      /* ignore parse errors — keep raw text available via message */
    }
    throw Object.assign(new Error(`Stream request failed: ${response.status}`), {
      status: response.status,
      body: parsed,
    });
  }

  const reader = response.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";
  let currentEvent = "message";
  let currentDataLines: string[] = [];

  const flushCurrentEvent = (): StreamEvent | null => {
    if (!currentDataLines.length) {
      return null;
    }
    const rawData = currentDataLines.join("\n");
    const nextEvent = currentEvent;
    currentEvent = "message";
    currentDataLines = [];
    try {
      return { event: nextEvent, data: JSON.parse(rawData) };
    } catch {
      return { event: nextEvent, data: { raw: rawData } };
    }
  };

  const processLine = (rawLine: string): StreamEvent | null => {
    const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
    if (line.startsWith("event:")) {
      currentEvent = line.slice("event:".length).trim();
      return null;
    }
    if (line.startsWith("data:")) {
      currentDataLines.push(line.slice("data:".length).trimStart());
      return null;
    }
    if (line === "") {
      return flushCurrentEvent();
    }
    return null;
  };

  const waitForNextPaint = async () => {
    await new Promise<void>((resolve) => {
      if (
        typeof window !== "undefined" &&
        typeof window.requestAnimationFrame === "function"
      ) {
        window.requestAnimationFrame(() => resolve());
        return;
      }
      setTimeout(resolve, 0);
    });
  };

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    const parsedEvents: StreamEvent[] = [];

    let newlineIndex = buffer.indexOf("\n");
    while (newlineIndex !== -1) {
      const nextEventChunk = processLine(buffer.slice(0, newlineIndex));
      if (nextEventChunk) {
        parsedEvents.push(nextEventChunk);
      }
      buffer = buffer.slice(newlineIndex + 1);
      newlineIndex = buffer.indexOf("\n");
    }

    for (let index = 0; index < parsedEvents.length; index += 1) {
      if (index > 0) {
        await waitForNextPaint();
      }
      yield parsedEvents[index];
    }

    if (done) {
      break;
    }
  }

  const trailingEvents: StreamEvent[] = [];
  if (buffer.length) {
    const finalBufferedEvent = processLine(buffer);
    if (finalBufferedEvent) {
      trailingEvents.push(finalBufferedEvent);
    }
  }

  const trailingEvent = flushCurrentEvent();
  if (trailingEvent) {
    trailingEvents.push(trailingEvent);
  }

  for (let index = 0; index < trailingEvents.length; index += 1) {
    if (index > 0) {
      await waitForNextPaint();
    }
    yield trailingEvents[index];
  }
}
