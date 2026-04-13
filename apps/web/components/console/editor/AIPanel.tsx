"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Send, X, Sparkles, Loader2 } from "lucide-react";
import { apiStream } from "@/lib/api-stream";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AIPanelProps {
  pageId: string;
  pageContext: string;
  selectedText?: string;
  onInsertToEditor?: (text: string) => void;
  onClose: () => void;
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AIPanel({
  pageId,
  pageContext,
  selectedText,
  onInsertToEditor,
  onClose,
}: AIPanelProps) {
  const t = useTranslations("console-notebooks");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamContent, setStreamContent] = useState("");
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

    const controller = new AbortController();
    abortRef.current = controller;

    let fullContent = "";
    try {
      for await (const { event, data } of apiStream(
        "/api/v1/ai/notebook/ask",
        {
          page_id: pageId,
          message: text,
          context: selectedText || "",
          history: newMessages.map((m) => ({ role: m.role, content: m.content })),
        },
        controller.signal,
      )) {
        if (event === "token" && data.content) {
          fullContent += data.content as string;
          setStreamContent(fullContent);
        } else if (event === "message_done") {
          fullContent = (data.content as string) || fullContent;
        } else if (event === "error") {
          fullContent = `Error: ${data.message || "Unknown error"}`;
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        fullContent = fullContent || "Connection failed.";
      }
    }

    setMessages((prev) => [...prev, { role: "assistant", content: fullContent }]);
    setStreamContent("");
    setStreaming(false);
    abortRef.current = null;
  }, [input, streaming, messages, pageId, selectedText]);

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
