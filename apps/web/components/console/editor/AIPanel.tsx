"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Send, X, Sparkles, Loader2 } from "lucide-react";
import { apiStream } from "@/lib/api-stream";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AIPanelProps {
  notebookId?: string;
  pageId?: string;
  selectedText?: string;
  onInsertToEditor?: (text: string) => void;
  onClose: () => void;
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  sources?: ChatSource[];
}

interface ChatSource {
  type: string;
  id: string;
  title: string;
}

function normalizeSources(value: unknown): ChatSource[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((item) => {
      if (!item || typeof item !== "object") {
        return null;
      }

      const source = item as Record<string, unknown>;
      const type = String(source.type || "").trim();
      const id = String(source.id || "").trim();
      const title = String(source.title || "").trim();

      if (!type && !id && !title) {
        return null;
      }

      return {
        type: type || "source",
        id,
        title,
      };
    })
    .filter((item): item is ChatSource => item !== null);
}

function formatSourceType(type: string): string {
  return type.replaceAll("_", " ");
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AIPanel({
  notebookId,
  pageId,
  selectedText,
  onInsertToEditor,
  onClose,
}: AIPanelProps) {
  const t = useTranslations("console-notebooks");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamContent, setStreamContent] = useState("");
  const [streamSources, setStreamSources] = useState<ChatSource[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamContent]);

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;

    const userMsg: ChatMessage = { role: "user", content: text };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    setInput("");
    setStreaming(true);
    setStreamContent("");
    setStreamSources([]);

    const controller = new AbortController();
    abortRef.current = controller;

    let fullContent = "";
    let fullSources: ChatSource[] = [];
    try {
      for await (const { event, data } of apiStream(
        "/api/v1/ai/notebook/ask",
        {
          notebook_id: notebookId,
          page_id: pageId,
          message: text,
          context: selectedText || "",
          history: newMessages.map((m) => ({ role: m.role, content: m.content })),
        },
        controller.signal,
      )) {
        if (event === "message_start") {
          fullSources = normalizeSources(data.sources);
          setStreamSources(fullSources);
        } else if (event === "token" && data.content) {
          fullContent += data.content as string;
          setStreamContent(fullContent);
        } else if (event === "message_done") {
          fullContent = (data.content as string) || fullContent;
          const doneSources = normalizeSources(data.sources);
          if (doneSources.length > 0) {
            fullSources = doneSources;
            setStreamSources(doneSources);
          }
        } else if (event === "error") {
          fullContent = `Error: ${data.message || "Unknown error"}`;
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        fullContent = fullContent || "Connection failed.";
      }
    }

    setMessages((prev) => [
      ...prev,
      { role: "assistant", content: fullContent, sources: fullSources },
    ]);
    setStreamContent("");
    setStreamSources([]);
    setStreaming(false);
    abortRef.current = null;
  }, [input, streaming, messages, notebookId, pageId, selectedText]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        void handleSend();
      }
    },
    [handleSend],
  );

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const renderSources = useCallback(
    (sources: ChatSource[]) => {
      if (sources.length === 0) {
        return null;
      }

      return (
        <div className="ai-panel-sources">
          <span className="ai-panel-sources-label">{t("ai.sources")}</span>
          {sources.map((source, index) => (
            <span
              key={`${source.type}-${source.id || source.title}-${index}`}
              className="ai-panel-source-pill"
            >
              <span className="ai-panel-source-type">{formatSourceType(source.type)}</span>
              <span className="ai-panel-source-title">{source.title || source.id}</span>
            </span>
          ))}
        </div>
      );
    },
    [t],
  );

  return (
    <div className="ai-panel">
      {/* Header */}
      <div className="ai-panel-header">
        <div className="ai-panel-header-left">
          <Sparkles size={16} />
          <span>{t("ai.title")}</span>
        </div>
        <button type="button" className="ai-panel-close" onClick={onClose} aria-label="Close">
          <X size={16} />
        </button>
      </div>

      {/* Messages */}
      <div className="ai-panel-messages">
        {messages.length === 0 && !streaming && (
          <div className="ai-panel-empty">
            <Sparkles size={24} />
            <p>{t("ai.emptyHint")}</p>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`ai-panel-msg ai-panel-msg-${msg.role}`}>
            <div className="ai-panel-msg-content">{msg.content}</div>
            {msg.role === "assistant" && renderSources(msg.sources || [])}
            {msg.role === "assistant" && onInsertToEditor && (
              <button
                type="button"
                className="ai-panel-insert-btn"
                onClick={() => onInsertToEditor(msg.content)}
              >
                {t("ai.insertToEditor")}
              </button>
            )}
          </div>
        ))}

        {streaming && streamContent && (
          <div className="ai-panel-msg ai-panel-msg-assistant">
            <div className="ai-panel-msg-content">{streamContent}</div>
            {renderSources(streamSources)}
          </div>
        )}

        {streaming && !streamContent && (
          <div className="ai-panel-msg ai-panel-msg-assistant">
            <Loader2 size={16} className="ai-panel-spinner" />
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="ai-panel-input-area">
        <textarea
          ref={inputRef}
          className="ai-panel-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={t("ai.placeholder")}
          rows={2}
          disabled={streaming}
        />
        {streaming ? (
          <button type="button" className="ai-panel-send-btn" onClick={handleStop}>
            <X size={16} />
          </button>
        ) : (
          <button
            type="button"
            className="ai-panel-send-btn"
            onClick={handleSend}
            disabled={!input.trim()}
          >
            <Send size={16} />
          </button>
        )}
      </div>
    </div>
  );
}
