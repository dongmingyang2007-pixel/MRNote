"use client";

import {
  type ComponentPropsWithoutRef,
  Fragment,
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { useTranslations } from "next-intl";

import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

import { apiPost } from "@/lib/api";
import {
  type InspectorSection,
  type InspectorTab,
  type Message,
  type MessageInspectorOverride,
  type MemoryWriteSummaryItem,
  type SearchSource,
  type SpeechResponse,
  createAudioPlayer,
} from "./chat-types";
import { ChatMessageMetaRail } from "./chat/ChatMessageMetaRail";
import {
  buildChatMetaRailItems,
  buildMemoryWriteSummary,
  buildThinkingSummary,
} from "./chat/chat-view-models";
import { protectPartialFenceBlocks } from "./chat-markdown-normalization";

/* ------------------------------------------------------------------ */
/*  AnimatedMessageText                                                */
/* ------------------------------------------------------------------ */

function AnimatedMessageText({
  text,
  animate,
  streaming = false,
}: {
  text: string;
  animate: boolean;
  streaming?: boolean;
}) {
  const segments = Array.from(text);
  const shouldAnimate = animate && !streaming;
  const [visibleCount, setVisibleCount] = useState(() =>
    shouldAnimate ? 0 : segments.length,
  );

  useEffect(() => {
    if (!shouldAnimate || segments.length === 0) {
      return;
    }

    const msPerChar =
      segments.length > 240 ? 6 : segments.length > 120 ? 12 : 22;
    let rafId = 0;
    const start = performance.now();

    const tick = (now: number) => {
      const nextCount = Math.min(
        segments.length,
        Math.max(1, Math.floor((now - start) / msPerChar)),
      );
      setVisibleCount(nextCount);
      if (nextCount < segments.length) {
        rafId = window.requestAnimationFrame(tick);
      }
    };

    rafId = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(rafId);
  }, [segments.length, shouldAnimate, text]);

  const displayCount = shouldAnimate ? visibleCount : segments.length;
  const visibleText = segments.slice(0, displayCount).join("");
  const renderableText = protectPartialFenceBlocks(visibleText);
  const showCursor =
    streaming || (shouldAnimate && displayCount < segments.length);

  return (
    <div className="chat-markdown">
      {streaming ? (
        <div className="chat-streaming-plaintext">{renderableText}</div>
      ) : (
        <ReactMarkdown
          remarkPlugins={[remarkGfm, remarkBreaks, remarkMath]}
          rehypePlugins={[rehypeKatex]}
          components={{
            a: ({ href, children }) => (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  color: "var(--console-accent, #2563EB)",
                  textDecoration: "underline",
                }}
              >
                {children}
              </a>
            ),
          }}
        >
          {renderableText}
        </ReactMarkdown>
      )}
      {showCursor ? <span className="chat-inline-cursor">&#x2588;</span> : null}
    </div>
  );
}

const CITATION_PATTERN = /\[ref_(\d+)\]/g;

type MarkdownNode = {
  type?: string;
  value?: string;
  url?: string;
  title?: string | null;
  children?: MarkdownNode[];
};

function getSourceDisplayIndex(
  source: SearchSource,
  fallbackIndex: number,
): number {
  return source.index > 0 ? source.index : fallbackIndex;
}

function getSourceCardId(messageId: string, sourceIndex: number): string {
  return `chat-source-${messageId}-${sourceIndex}`;
}

function getSourceSummaryId(messageId: string): string {
  return `chat-source-summary-${messageId}`;
}

function MarkdownLink({ href, children }: ComponentPropsWithoutRef<"a">) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      style={{
        color: "var(--console-accent, #2563EB)",
        textDecoration: "underline",
      }}
    >
      {children}
    </a>
  );
}

function buildCitationSnippetMap(text: string): Map<number, string> {
  const snippets = new Map<number, string>();
  const blocks = text
    .split(/\n+/)
    .map((block) => block.trim())
    .filter(Boolean);

  for (const block of blocks) {
    const indices = Array.from(block.matchAll(CITATION_PATTERN)).map((match) =>
      Number.parseInt(match[1] || "0", 10),
    );
    if (!indices.length) {
      continue;
    }
    const cleaned = block
      .replace(CITATION_PATTERN, "")
      .replace(/\s+/g, " ")
      .trim();
    if (!cleaned) {
      continue;
    }
    for (const index of indices) {
      if (!snippets.has(index)) {
        snippets.set(index, cleaned);
      }
    }
  }

  return snippets;
}

function replaceCitationTextNode(
  node: MarkdownNode,
  {
    messageId,
    sourceIndices,
  }: {
    messageId: string;
    sourceIndices: Set<number>;
  },
): MarkdownNode[] {
  const value = typeof node.value === "string" ? node.value : "";
  if (!value) {
    return [node];
  }

  const nextNodes: MarkdownNode[] = [];
  let lastIndex = 0;

  for (const match of value.matchAll(CITATION_PATTERN)) {
    const raw = match[0];
    const matchIndex = match.index ?? 0;
    const citationIndex = Number.parseInt(match[1] || "0", 10);
    if (!sourceIndices.has(citationIndex)) {
      continue;
    }
    if (matchIndex > lastIndex) {
      nextNodes.push({
        type: "text",
        value: value.slice(lastIndex, matchIndex),
      });
    }
    nextNodes.push({
      type: "link",
      url: `#${getSourceCardId(messageId, citationIndex)}`,
      title: raw,
      children: [{ type: "text", value: `[${citationIndex}]` }],
    });
    lastIndex = matchIndex + raw.length;
  }

  if (!nextNodes.length) {
    return [node];
  }

  if (lastIndex < value.length) {
    nextNodes.push({
      type: "text",
      value: value.slice(lastIndex),
    });
  }

  return nextNodes;
}

function injectCitationLinks(
  node: MarkdownNode,
  {
    messageId,
    sourceIndices,
  }: {
    messageId: string;
    sourceIndices: Set<number>;
  },
): void {
  if (!Array.isArray(node.children) || node.children.length === 0) {
    return;
  }

  const nextChildren: MarkdownNode[] = [];
  for (const child of node.children) {
    if (!child || typeof child !== "object") {
      nextChildren.push(child);
      continue;
    }

    if (child.type === "text") {
      nextChildren.push(
        ...replaceCitationTextNode(child, {
          messageId,
          sourceIndices,
        }),
      );
      continue;
    }

    if (
      child.type !== "link" &&
      child.type !== "linkReference" &&
      child.type !== "definition" &&
      child.type !== "inlineCode" &&
      child.type !== "code" &&
      child.type !== "math" &&
      child.type !== "inlineMath" &&
      child.type !== "html"
    ) {
      injectCitationLinks(child, {
        messageId,
        sourceIndices,
      });
    }

    nextChildren.push(child);
  }

  node.children = nextChildren;
}

function createCitationRemarkPlugin(
  messageId: string,
  sourceIndices: Set<number>,
) {
  return function remarkCitationLinks() {
    return (tree: MarkdownNode) => {
      injectCitationLinks(tree, {
        messageId,
        sourceIndices,
      });
    };
  };
}

function formatSourceDomain(source: SearchSource): string {
  const siteName = source.site_name?.trim();
  const domain = source.domain.trim();
  if (siteName && domain && siteName !== domain) {
    return `${siteName} · ${domain}`;
  }
  return siteName || domain;
}

function getSourceIconUrl(source: SearchSource): string | null {
  const explicitIcon = source.icon?.trim();
  if (explicitIcon) {
    return explicitIcon;
  }

  try {
    return new URL("/favicon.ico", source.url).toString();
  } catch {
    return null;
  }
}

function resolveSourceSummary(
  source: SearchSource,
  citationSnippets: Map<number, string>,
  fallbackIndex: number,
): string | null {
  const explicitSummary = source.summary?.trim();
  if (explicitSummary) {
    return explicitSummary;
  }
  return (
    citationSnippets.get(getSourceDisplayIndex(source, fallbackIndex)) || null
  );
}

function SourceFavicon({ source }: { source: SearchSource }) {
  const [imageFailed, setImageFailed] = useState(false);
  const iconUrl = getSourceIconUrl(source);
  const fallbackLabel = (
    source.site_name ||
    source.domain ||
    source.title ||
    "?"
  )
    .trim()
    .charAt(0)
    .toUpperCase();

  return (
    <span className="chat-source-favicon" aria-hidden="true">
      {iconUrl && !imageFailed ? (
        /* eslint-disable-next-line @next/next/no-img-element */
        <img
          className="chat-source-favicon-img"
          src={iconUrl}
          alt=""
          onError={() => setImageFailed(true)}
        />
      ) : (
        <span className="chat-source-favicon-fallback">
          {fallbackLabel || "?"}
        </span>
      )}
    </span>
  );
}

function SourceAwareAssistantMarkdown({
  message,
  content,
  sourceEntries,
  onOpenInspector,
}: {
  message: Message;
  content: string;
  sourceEntries: Map<
    number,
    {
      source: SearchSource;
      displayIndex: number;
      previewSummary: string;
    }
  >;
  onOpenInspector: (payload: {
    tab: InspectorTab;
    messageId: string;
    section?: InspectorSection;
  }) => void;
}) {
  const citationPlugin = createCitationRemarkPlugin(
    message.id,
    new Set(sourceEntries.keys()),
  );
  const citationHrefMap = new Map(
    Array.from(sourceEntries.values()).map((entry) => [
      `#${getSourceCardId(message.id, entry.displayIndex)}`,
      entry,
    ]),
  );

  return (
    <div className="chat-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkBreaks, remarkMath, citationPlugin]}
        rehypePlugins={[rehypeKatex]}
        components={{
          a: ({ href, children }) => {
            const entry = href ? citationHrefMap.get(href) : undefined;
            if (entry) {
              return (
                <CitationAnchor
                  messageId={message.id}
                  source={entry.source}
                  displayIndex={entry.displayIndex}
                  previewSummary={entry.previewSummary}
                  onOpenInspector={onOpenInspector}
                />
              );
            }

            return <MarkdownLink href={href}>{children}</MarkdownLink>;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function CitationAnchor({
  messageId,
  source,
  displayIndex,
  previewSummary,
  onOpenInspector,
}: {
  messageId: string;
  source: SearchSource;
  displayIndex: number;
  previewSummary: string;
  onOpenInspector: (payload: {
    tab: InspectorTab;
    messageId: string;
    section?: InspectorSection;
  }) => void;
}) {
  return (
    <span className="chat-citation-anchor-wrap">
      <button
        type="button"
        className="chat-citation-anchor"
        title={source.title}
        onClick={() =>
          onOpenInspector({
            tab: "context",
            messageId,
            section: "sources",
          })
        }
      >
        [{displayIndex}]
      </button>
      <span className="chat-citation-preview" role="tooltip">
        <span className="chat-citation-preview-title">{source.title}</span>
        <span className="chat-citation-preview-meta">
          {formatSourceDomain(source)}
        </span>
        <span className="chat-citation-preview-summary">{previewSummary}</span>
      </span>
    </span>
  );
}

function SourceSummaryTrigger({
  messageId,
  sources,
  t,
  onOpenInspector,
}: {
  messageId: string;
  sources: SearchSource[];
  t: (key: string, values?: Record<string, string | number>) => string;
  onOpenInspector: (payload: {
    tab: InspectorTab;
    messageId: string;
    section?: InspectorSection;
  }) => void;
}) {
  if (!sources.length) {
    return null;
  }

  const previewSources = sources.slice(0, 3);

  return (
    <button
      type="button"
      id={getSourceSummaryId(messageId)}
      className="chat-source-summary-trigger"
      aria-label={t("inspector.meta.sources", { count: sources.length })}
      onClick={() =>
        onOpenInspector({
          tab: "context",
          messageId,
          section: "sources",
        })
      }
    >
      <span className="chat-source-summary-stack" aria-hidden="true">
        {previewSources.map((source, index) => (
          <span
            key={`${source.url}-${index}`}
            className="chat-source-summary-stack-item"
            style={{ zIndex: previewSources.length - index }}
          >
            <SourceFavicon source={source} />
          </span>
        ))}
      </span>
      <span className="chat-source-summary-label">{t("sourcesLabel")}</span>
      <span className="chat-source-summary-count">{sources.length}</span>
    </button>
  );
}

function AssistantMessageBody({
  message,
  t,
  onOpenInspector,
}: {
  message: Message;
  t: (key: string, values?: Record<string, string | number>) => string;
  onOpenInspector: (payload: {
    tab: InspectorTab;
    messageId: string;
    section?: InspectorSection;
  }) => void;
}) {
  const sources = message.sources ?? [];
  const normalizedContent = message.content;
  if (message.isStreaming && !message.content.trim()) {
    return (
      <span className="chat-streaming-placeholder" aria-hidden="true">
        <span className="typing-dot" />
        <span className="typing-dot" />
        <span className="typing-dot" />
      </span>
    );
  }

  if (!sources.length || message.isStreaming) {
    return (
      <AnimatedMessageText
        text={message.content}
        animate={Boolean(message.animateOnMount)}
        streaming={Boolean(message.isStreaming)}
      />
    );
  }

  const citationSnippets = buildCitationSnippetMap(normalizedContent);
  const sourceEntries = new Map(
    sources.map((source, index) => {
      const displayIndex = getSourceDisplayIndex(source, index + 1);
      const previewSummary =
        resolveSourceSummary(source, citationSnippets, index + 1) ||
        t("sourceNoSummary");
      return [displayIndex, { source, displayIndex, previewSummary }];
    }),
  );
  const hasCitationAnchors = Array.from(
    normalizedContent.matchAll(CITATION_PATTERN),
  ).some((match) => sourceEntries.has(Number.parseInt(match[1] || "0", 10)));

  return (
    <>
      <SourceAwareAssistantMarkdown
        message={message}
        content={normalizedContent}
        sourceEntries={sourceEntries}
        onOpenInspector={onOpenInspector}
      />
      {!hasCitationAnchors ? (
        <span className="chat-citation-inline-list">
          {" "}
          {t("sourceReferencePrefix")}{" "}
          {sources.map((source, index) => {
            const displayIndex = getSourceDisplayIndex(source, index + 1);
            return (
              <Fragment key={`${source.url}-${displayIndex}`}>
                {index > 0 ? " " : null}
                <CitationAnchor
                  messageId={message.id}
                  source={source}
                  displayIndex={displayIndex}
                  previewSummary={
                    resolveSourceSummary(source, citationSnippets, index + 1) ||
                    t("sourceNoSummary")
                  }
                  onOpenInspector={onOpenInspector}
                />
              </Fragment>
            );
          })}
        </span>
      ) : null}
    </>
  );
}

function formatMemoryBadgeLabel(
  item: MemoryWriteSummaryItem,
  t: (key: string, values?: Record<string, string | number>) => string,
): string {
  switch (item.badgeKey) {
    case "long_term":
      return t("inspector.memory.badge.longTerm");
    case "temporary":
      return t("inspector.memory.badge.temporary");
    case "merged":
      return t("inspector.memory.badge.merged");
    default:
      return t("inspector.memory.badge.notWritten");
  }
}

function formatMemoryActionLabel(
  triageAction: string | null,
  t: (key: string, values?: Record<string, string | number>) => string,
): string {
  switch (triageAction) {
    case "create":
      return t("memory.actionCreate");
    case "append":
      return t("memory.actionAppend");
    case "merge":
      return t("memory.actionMerge");
    case "replace":
      return t("memory.actionReplace");
    case "discard":
      return t("memory.actionDiscard");
    default:
      return t("memory.resultUnknown");
  }
}

function buildMemoryCardSummary(
  items: MemoryWriteSummaryItem[],
  t: (key: string, values?: Record<string, string | number>) => string,
): string {
  const longTermCount = items.filter((item) => item.badgeKey === "long_term").length;
  const temporaryCount = items.filter((item) => item.badgeKey === "temporary").length;
  const mergedCount = items.filter((item) => item.badgeKey === "merged").length;
  const notWrittenCount = items.filter((item) => item.badgeKey === "not_written").length;

  const parts: string[] = [];
  if (longTermCount) {
    parts.push(t("memory.summary.longTerm", { count: longTermCount }));
  }
  if (temporaryCount) {
    parts.push(t("memory.summary.temporary", { count: temporaryCount }));
  }
  if (mergedCount) {
    parts.push(t("memory.summary.merged", { count: mergedCount }));
  }
  if (notWrittenCount) {
    parts.push(t("memory.summary.notWritten", { count: notWrittenCount }));
  }

  return parts.join("；");
}

function InlineThinkingBlock({
  content,
  streaming = false,
  t,
}: {
  content: string;
  streaming?: boolean;
  t: (key: string, values?: Record<string, string | number>) => string;
}) {
  const [isOpen, setIsOpen] = useState(Boolean(streaming && content.trim()));
  const normalizedContent = content;

  return (
    <section className={`chat-thinking-inline${isOpen ? " is-open" : ""}`}>
      <button
        type="button"
        className="chat-thinking-inline-toggle"
        onClick={() => setIsOpen((current) => !current)}
        aria-expanded={isOpen}
      >
        <span className="chat-thinking-inline-icon" aria-hidden="true">
          <svg
            width={14}
            height={14}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M12 3a6 6 0 0 0-3.47 10.9c.51.38.97 1.03 1.1 1.72L9.75 16h4.5l.12-.38c.13-.69.59-1.34 1.1-1.72A6 6 0 0 0 12 3Z" />
            <path d="M10 20h4" />
            <path d="M10.5 16h3" />
          </svg>
        </span>
        <span className="chat-thinking-inline-copy">
          <span className="chat-thinking-inline-label">
            {t("thinking.inlineLabel")}
          </span>
          <span className="chat-thinking-inline-hint">
            {isOpen ? t("thinking.inlineCollapse") : t("thinking.inlineExpand")}
          </span>
        </span>
        <span className="chat-thinking-inline-chevron" aria-hidden="true">
          <svg
            width={14}
            height={14}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d={isOpen ? "m18 15-6-6-6 6" : "m6 9 6 6 6-6"} />
          </svg>
        </span>
      </button>
      {isOpen ? (
        <div className="chat-thinking-inline-body">
          <div className="chat-thinking-inline-markdown chat-markdown">
            {streaming ? (
              <div className="chat-streaming-plaintext">{normalizedContent}</div>
            ) : (
              <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkBreaks, remarkMath]}
                rehypePlugins={[rehypeKatex]}
                components={{
                  a: ({ href, children }) => (
                    <a
                      href={href}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{
                        color: "var(--console-accent, #2563EB)",
                        textDecoration: "underline",
                      }}
                    >
                      {children}
                    </a>
                  ),
                }}
              >
                {normalizedContent}
              </ReactMarkdown>
            )}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function MemorySummaryCard({
  message,
  items,
  t,
  onOpenInspector,
}: {
  message: Message;
  items: MemoryWriteSummaryItem[];
  t: (key: string, values?: Record<string, string | number>) => string;
  onOpenInspector: (payload: {
    tab: InspectorTab;
    messageId: string;
    section?: InspectorSection;
  }) => void;
}) {
  const writtenItems = items.filter((item) => item.triageAction !== "discard");

  if (!writtenItems.length) {
    return null;
  }

  const visibleItems = writtenItems.slice(0, 3);
  const summary = buildMemoryCardSummary(writtenItems, t);

  return (
    <section className="chat-memory-summary-card">
      <div className="chat-memory-summary-header">
        <div className="chat-memory-summary-headline">
          <span className="chat-memory-summary-icon" aria-hidden="true">
            <svg
              width={18}
              height={18}
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12 8v4l3 3" />
              <circle cx="12" cy="12" r="9" />
            </svg>
          </span>
          <div className="chat-memory-summary-copy">
            <div className="chat-memory-summary-title">{t("memory.remembered")}</div>
            <div className="chat-memory-summary-subtitle">
              {summary || t("inspector.memory.description")}
            </div>
          </div>
        </div>
        <button
          type="button"
          className="chat-memory-summary-open"
          onClick={() =>
            onOpenInspector({
              tab: "memory_write",
              messageId: message.id,
            })
          }
        >
          {t("memory.openInspector")}
        </button>
      </div>

      <div className="chat-memory-summary-list">
        {visibleItems.map((item) => {
          const importance = Number.isFinite(item.importance)
            ? Math.round(item.importance * 100)
            : null;

          return (
            <article
              key={item.id}
              className={`chat-memory-summary-item is-${item.badgeKey}`}
            >
              <div className="chat-memory-summary-item-top">
                <div className="chat-memory-summary-item-category">
                  {item.category || t("retrievalKindUnknown")}
                </div>
                <div className="chat-memory-summary-item-badges">
                  <span
                    className={`chat-memory-summary-badge is-${item.badgeKey}`}
                  >
                    {formatMemoryBadgeLabel(item, t)}
                  </span>
                  {importance !== null ? (
                    <span className="chat-memory-summary-score">
                      {t("memory.importanceValue", { score: importance })}
                    </span>
                  ) : null}
                </div>
              </div>
              <div className="chat-memory-summary-item-fact">{item.fact}</div>
              <div className="chat-memory-summary-item-meta">
                {t("memory.decisionPrefix")}
                {formatMemoryActionLabel(item.triageAction, t)}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export interface ChatMessageListProps {
  messages: Message[];
  onMessagesChange: (msgs: Message[]) => void;
  isTyping: boolean;
  isCompactViewport?: boolean;
  conversationId?: string | null;
  noConversation: boolean;
  messageInspectorOverrides: Record<string, MessageInspectorOverride>;
  onOpenInspector: (payload: {
    tab: InspectorTab;
    messageId: string;
    section?: InspectorSection;
  }) => void;
  onError?: (message: string) => void;
}

export interface ChatMessageListHandle {
  appendMessage: (msg: Message) => void;
  updateMessage: (id: string, updater: (prev: string) => string) => void;
  updateReasoning: (id: string, updater: (prev: string) => string) => void;
  finalizeMessage: (
    tempId: string,
    final: {
      id: string;
      isStreaming: boolean;
      content?: string;
      reasoningContent?: string | null;
      memories_extracted?: string;
      memory_write_preview?: Message["memory_write_preview"];
      sources?: SearchSource[];
      retrievalTrace?: Message["retrievalTrace"];
    },
  ) => void;
  setMessages: (msgs: Message[]) => void;
  replaceMessages: (updater: (prev: Message[]) => Message[]) => void;
  playReadAloud: (messageId: string, audioBase64?: string) => void;
  stopPlayback: () => void;
}

/* ------------------------------------------------------------------ */
/*  ChatMessageList                                                    */
/* ------------------------------------------------------------------ */

export const ChatMessageList = forwardRef<
  ChatMessageListHandle,
  ChatMessageListProps
>(function ChatMessageList(
  {
    messages,
    onMessagesChange,
    isTyping,
    isCompactViewport = false,
    conversationId,
    noConversation,
    messageInspectorOverrides,
    onOpenInspector,
    onError,
  },
  ref,
) {
  const t = useTranslations("console-chat");
  const tCommon = useTranslations("common");

  /* ---------- keep a ref to the latest messages for imperative handle ---------- */
  const messagesRef = useRef(messages);
  messagesRef.current = messages;

  /* ---------- read-aloud state / refs ---------- */
  const [loadingReadAloudId, setLoadingReadAloudId] = useState<string | null>(
    null,
  );
  const [readingMessageId, setReadingMessageId] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);
  const conversationIdRef = useRef(conversationId);
  const readAloudRequestSeqRef = useRef(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  conversationIdRef.current = conversationId;

  /* ---------- read-aloud helpers ---------- */

  const releaseAudioPlayer = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.onended = null;
      audioRef.current.onerror = null;
    }
    audioRef.current = null;
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }
    setReadingMessageId(null);
  }, []);

  const stopReadAloud = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
    }
    releaseAudioPlayer();
  }, [releaseAudioPlayer]);

  useEffect(() => {
    return () => {
      readAloudRequestSeqRef.current += 1;
      stopReadAloud();
    };
  }, [conversationId, stopReadAloud]);

  const playMessageAudio = useCallback(
    (base64Audio: string, messageId: string) => {
      stopReadAloud();
      try {
        const { audio, url } = createAudioPlayer(base64Audio);
        audioRef.current = audio;
        audioUrlRef.current = url;
        setReadingMessageId(messageId);
        audio.onended = () => {
          releaseAudioPlayer();
        };
        audio.onerror = () => {
          releaseAudioPlayer();
        };
        void audio.play().catch(() => {
          releaseAudioPlayer();
        });
      } catch {
        releaseAudioPlayer();
      }
    },
    [releaseAudioPlayer, stopReadAloud],
  );

  const cacheMessageAudio = useCallback(
    (messageId: string, audioBase64: string) => {
      onMessagesChange(
        messagesRef.current.map((message) =>
          message.id === messageId ? { ...message, audioBase64 } : message,
        ),
      );
    },
    [onMessagesChange],
  );

  const handleReadAloud = useCallback(
    async (message: Message) => {
      const text = message.content.trim();
      if (!conversationId || !text) {
        return;
      }

      if (readingMessageId === message.id) {
        stopReadAloud();
        return;
      }

      const requestConversationId = conversationIdRef.current;
      const requestSeq = ++readAloudRequestSeqRef.current;

      if (message.audioBase64) {
        if (
          readAloudRequestSeqRef.current !== requestSeq ||
          conversationIdRef.current !== requestConversationId
        ) {
          return;
        }
        playMessageAudio(message.audioBase64, message.id);
        return;
      }

      setLoadingReadAloudId(message.id);
      try {
        const data = await apiPost<SpeechResponse>(
          `/api/v1/chat/conversations/${conversationId}/speech`,
          { content: text },
        );
        if (
          readAloudRequestSeqRef.current !== requestSeq ||
          conversationIdRef.current !== requestConversationId
        ) {
          return;
        }
        if (!data.audio_response) {
          throw new Error("missing audio response");
        }
        cacheMessageAudio(message.id, data.audio_response);
        playMessageAudio(data.audio_response, message.id);
      } catch (error) {
        const errorMessage =
          error instanceof Error ? error.message : "Read-aloud failed";
        onError?.(errorMessage);
      } finally {
        if (
          readAloudRequestSeqRef.current !== requestSeq ||
          conversationIdRef.current !== requestConversationId
        ) {
          return;
        }
        setLoadingReadAloudId((current) =>
          current === message.id ? null : current,
        );
      }
    },
    [
      cacheMessageAudio,
      conversationId,
      onError,
      playMessageAudio,
      readingMessageId,
      stopReadAloud,
    ],
  );

  /* ---------- scroll-to-bottom ---------- */

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
  }, [messages, isTyping]);

  /* ---------- cleanup on unmount ---------- */

  useEffect(() => () => stopReadAloud(), [stopReadAloud]);

  /* ---------- imperative handle ---------- */

  useImperativeHandle(
    ref,
    () => ({
      appendMessage(msg: Message) {
        onMessagesChange([...messagesRef.current, msg]);
      },
      updateMessage(id: string, updater: (prev: string) => string) {
        onMessagesChange(
          messagesRef.current.map((m) =>
            m.id === id ? { ...m, content: updater(m.content) } : m,
          ),
        );
      },
      updateReasoning(id: string, updater: (prev: string) => string) {
        onMessagesChange(
          messagesRef.current.map((m) =>
            m.id === id
              ? { ...m, reasoningContent: updater(m.reasoningContent ?? "") }
              : m,
          ),
        );
      },
      finalizeMessage(
        tempId: string,
        final: {
          id: string;
          isStreaming: boolean;
          content?: string;
          reasoningContent?: string | null;
          memories_extracted?: string;
          memory_write_preview?: Message["memory_write_preview"];
          sources?: SearchSource[];
          retrievalTrace?: Message["retrievalTrace"];
        },
      ) {
        onMessagesChange(
          messagesRef.current.map((m) =>
            m.id === tempId ? { ...m, ...final } : m,
          ),
        );
      },
      setMessages(msgs: Message[]) {
        onMessagesChange(msgs);
      },
      replaceMessages(updater: (prev: Message[]) => Message[]) {
        onMessagesChange(updater(messagesRef.current));
      },
      playReadAloud(messageId: string, audioBase64?: string) {
        if (audioBase64) {
          cacheMessageAudio(messageId, audioBase64);
          playMessageAudio(audioBase64, messageId);
        } else {
          const msg = messagesRef.current.find((m) => m.id === messageId);
          if (msg) {
            void handleReadAloud(msg);
          }
        }
      },
      stopPlayback() {
        stopReadAloud();
      },
    }),
    [
      cacheMessageAudio,
      handleReadAloud,
      onMessagesChange,
      playMessageAudio,
      stopReadAloud,
    ],
  );

  /* ---------- render ---------- */

  return (
    <div
      className="chat-messages"
      role="log"
      aria-live="polite"
      aria-busy={isTyping}
    >
      {messages.length === 0 && !isTyping && (
        <div className="chat-empty">
          {noConversation ? t("emptyHint") : t("emptyConversationHint")}
        </div>
      )}

      {messages.map((msg, index) => {
        const assistantSources =
          msg.role === "assistant" ? (msg.sources ?? []) : [];
        const showAvatar =
          msg.role === "assistant" &&
          (index === 0 || messages[index - 1]?.role !== "assistant");
        const showMessageActions =
          msg.role === "assistant" &&
          (msg.content.trim() ||
            msg.audioBase64 ||
            loadingReadAloudId === msg.id ||
            readingMessageId === msg.id);
        const metaRailItems =
          msg.role === "assistant"
            ? buildChatMetaRailItems(msg, messageInspectorOverrides, t)
            : [];
        const memorySummary =
          msg.role === "assistant"
            ? buildMemoryWriteSummary(msg, messageInspectorOverrides, t)
            : { count: 0, label: null, items: [] };
        const thinkingSummary =
          msg.role === "assistant"
            ? buildThinkingSummary(msg, t)
            : { label: null, content: null };
        const promotedMetaRailItems =
          msg.role === "assistant"
            ? metaRailItems.filter(
                (item) =>
                  item.key !== "sources" &&
                  item.key !== "memory_write" &&
                  item.key !== "thinking",
              )
            : metaRailItems;
        const inlineContextItem =
          msg.role === "assistant" && isCompactViewport
            ? promotedMetaRailItems.find((item) => item.key === "context") ?? null
            : null;
        const supportMetaRailItems = inlineContextItem
          ? promotedMetaRailItems.filter((item) => item.key !== "context")
          : promotedMetaRailItems;

        return (
          <div
            key={msg.id}
            className={`chat-message ${msg.role === "user" ? "is-user" : "is-assistant"}`}
          >
            {msg.role === "assistant" ? (
              <div
                className={`chat-avatar-ai${showAvatar ? "" : " is-ghost"}`}
                aria-hidden="true"
              >
                {showAvatar ? (
                  <span className="chat-avatar-ai-char">{tCommon("brand.glyph")}</span>
                ) : null}
              </div>
            ) : null}
            <div className="chat-message-wrapper">
              <div className="chat-message-stack">
                <div className="chat-message-primary">
                  {msg.role === "assistant" && thinkingSummary.content ? (
                    <InlineThinkingBlock
                      content={thinkingSummary.content}
                      streaming={Boolean(msg.isStreaming)}
                      t={t}
                    />
                  ) : null}
                  <div className="chat-bubble">
                    {msg.role === "assistant" ? (
                      <AssistantMessageBody
                        message={msg}
                        t={t}
                        onOpenInspector={onOpenInspector}
                      />
                    ) : (
                      <AnimatedMessageText
                        text={msg.content}
                        animate={Boolean(msg.animateOnMount)}
                        streaming={Boolean(msg.isStreaming)}
                      />
                    )}
                  </div>
                  {inlineContextItem ? (
                    <div className="chat-message-inline-actions">
                      <button
                        type="button"
                        className="chat-meta-chip chat-meta-chip--context chat-meta-chip--inline"
                        onClick={() =>
                          onOpenInspector({
                            tab: inlineContextItem.tab,
                            section: inlineContextItem.section,
                            messageId: msg.id,
                          })
                        }
                      >
                        <span className="chat-meta-chip-label">
                          {t("inspector.tabs.context")}
                        </span>
                      </button>
                    </div>
                  ) : null}
                  {showMessageActions ? (
                    <div className="chat-message-hover-actions">
                      <button
                        className={`chat-audio-btn ${readingMessageId === msg.id ? "is-active" : ""}`}
                        onClick={() => void handleReadAloud(msg)}
                        title={
                          readingMessageId === msg.id
                            ? t("voiceStop")
                            : t("voicePlay")
                        }
                        aria-label={
                          loadingReadAloudId === msg.id
                            ? t("voicePreparing")
                            : readingMessageId === msg.id
                              ? t("voiceStop")
                              : t("voicePlay")
                        }
                        disabled={loadingReadAloudId === msg.id}
                        type="button"
                      >
                        <svg
                          width={14}
                          height={14}
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth={2}
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        >
                          <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
                          <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
                        </svg>
                      </button>
                    </div>
                  ) : null}
                </div>
                {msg.role === "assistant" ? (
                  <div className="chat-message-support">
                    {memorySummary.count > 0 ? (
                      <MemorySummaryCard
                        message={msg}
                        items={memorySummary.items}
                        t={t}
                        onOpenInspector={onOpenInspector}
                      />
                    ) : null}
                    {assistantSources.length ? (
                      <div
                        className="chat-sources-compact"
                        aria-label={t("sourcesLabel")}
                      >
                        <SourceSummaryTrigger
                          messageId={msg.id}
                          sources={assistantSources}
                          t={t}
                          onOpenInspector={onOpenInspector}
                        />
                      </div>
                    ) : null}
                    <ChatMessageMetaRail
                      items={supportMetaRailItems}
                      messageId={msg.id}
                      onOpenInspector={onOpenInspector}
                    />
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        );
      })}

      {isTyping && (
        <div className="chat-message is-assistant">
          <div className="chat-avatar-ai is-ghost" aria-hidden="true" />
          <div className="chat-message-wrapper">
            <div className="chat-message-stack">
              <div className="chat-message-primary">
                <div className="chat-bubble is-typing">
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      <div ref={messagesEndRef} />
    </div>
  );
});
