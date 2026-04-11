"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useTranslations } from "next-intl";

import {
  apiDelete,
  apiGet,
  apiPatch,
  apiPost,
  apiPostFormData,
  isApiRequestError,
} from "@/lib/api";
import { apiStream } from "@/lib/api-stream";
import { getApiHttpBaseUrl } from "@/lib/env";
import type { PersistedRealtimeTurnPayload } from "@/hooks/useRealtimeVoice";
import RealtimeVoicePanel from "./RealtimeVoicePanel";
import { ChatMessageList, type ChatMessageListHandle } from "./ChatMessageList";
import { ChatInputBar } from "./ChatInputBar";
import { ChatModePanel } from "./ChatModePanel";
import { StandardVoiceControls } from "./StandardVoiceControls";
import { normalizeStreamingMarkdown } from "./chat-markdown-normalization";
import {
  ConversationInspector,
  type InspectorMemoryRecord,
} from "./chat/ConversationInspector";
import { getMessageInspectorOverrideKey } from "./chat/chat-view-models";
import {
  type ChatMode,
  type Message,
  type ApiMessage,
  type InspectorState,
  type ImageMessageResponse,
  type MessageInspectorOverride,
  type ProjectChatSettings,
  type PipelineConfigItem,
  type PipelineResponse,
  type CatalogModelItem,
  type LiveTranscriptUpdate,
  type MessageMemoryWriteDetail,
  VOICE_ACTIVE_STATES,
  getPipelineModelId,
  modelSupportsCapability,
  normalizeRetrievalTrace,
  normalizeSearchSources,
  toMessage,
  mergeAssistantMetadataPatch,
  getApiErrorMessage,
} from "./chat-types";

interface ChatInterfaceProps {
  conversationId?: string | null;
  projectId?: string | null;
  isConversationPending?: boolean;
  onConversationActivity?: (payload: {
    conversationId: string;
    previewText: string;
  }) => void;
  onConversationLoaded?: (payload: {
    conversationId: string;
    messages: ApiMessage[];
  }) => void;
}

function normalizeMemoryRecord(
  value: unknown,
): InspectorMemoryRecord | null {
  if (!value || typeof value !== "object") {
    return null;
  }

  const candidate = value as Record<string, unknown>;
  const id =
    typeof candidate.id === "string" && candidate.id.trim()
      ? candidate.id.trim()
      : "";
  const content =
    typeof candidate.content === "string" ? candidate.content.trim() : "";
  const category =
    typeof candidate.category === "string" ? candidate.category.trim() : "";
  const type =
    candidate.type === "temporary" ? "temporary" : "permanent";

  if (!id) {
    return null;
  }

  return {
    id,
    content,
    category,
    type,
    metadata_json:
      candidate.metadata_json && typeof candidate.metadata_json === "object"
        ? (candidate.metadata_json as Record<string, unknown>)
        : {},
    created_at:
      typeof candidate.created_at === "string" ? candidate.created_at : undefined,
    updated_at:
      typeof candidate.updated_at === "string" ? candidate.updated_at : undefined,
    confidence:
      typeof candidate.confidence === "number" ? candidate.confidence : null,
    observed_at:
      typeof candidate.observed_at === "string" ? candidate.observed_at : null,
    valid_from:
      typeof candidate.valid_from === "string" ? candidate.valid_from : null,
    valid_to:
      typeof candidate.valid_to === "string" ? candidate.valid_to : null,
    last_confirmed_at:
      typeof candidate.last_confirmed_at === "string"
        ? candidate.last_confirmed_at
        : null,
    evidences: Array.isArray(candidate.evidences)
      ? candidate.evidences.flatMap((item) => {
          if (!item || typeof item !== "object") {
            return [];
          }
          const evidence = item as Record<string, unknown>;
          const evidenceId =
            typeof evidence.id === "string" ? evidence.id.trim() : "";
          const quoteText =
            typeof evidence.quote_text === "string"
              ? evidence.quote_text.trim()
              : "";
          if (!evidenceId || !quoteText) {
            return [];
          }
          return [
            {
              id: evidenceId,
              quote_text: quoteText,
              source_type:
                typeof evidence.source_type === "string"
                  ? evidence.source_type
                  : null,
              confidence:
                typeof evidence.confidence === "number"
                  ? evidence.confidence
                  : null,
              created_at:
                typeof evidence.created_at === "string"
                  ? evidence.created_at
                  : null,
            },
          ];
        })
      : [],
    views: Array.isArray(candidate.views)
      ? candidate.views.flatMap((item) => {
          if (!item || typeof item !== "object") {
            return [];
          }
          const view = item as Record<string, unknown>;
          const viewId = typeof view.id === "string" ? view.id.trim() : "";
          const viewContent =
            typeof view.content === "string" ? view.content.trim() : "";
          if (!viewId || !viewContent) {
            return [];
          }
          return [
            {
              id: viewId,
              view_type:
                typeof view.view_type === "string" ? view.view_type : null,
              content: viewContent,
            },
          ];
        })
      : [],
    timeline_events: Array.isArray(candidate.timeline_events)
      ? candidate.timeline_events.flatMap((item) => {
          if (!item || typeof item !== "object") {
            return [];
          }
          const event = item as Record<string, unknown>;
          const eventId = typeof event.id === "string" ? event.id.trim() : "";
          const eventContent =
            typeof event.content === "string" ? event.content.trim() : "";
          if (!eventId || !eventContent) {
            return [];
          }
          return [
            {
              id: eventId,
              content: eventContent,
              observed_at:
                typeof event.observed_at === "string" ? event.observed_at : null,
              node_status:
                typeof event.node_status === "string" ? event.node_status : null,
            },
          ];
        })
      : [],
    write_history: Array.isArray(candidate.write_history)
      ? candidate.write_history.flatMap((item) => {
          if (!item || typeof item !== "object") {
            return [];
          }
          const history = item as Record<string, unknown>;
          const historyId =
            typeof history.id === "string" ? history.id.trim() : "";
          if (!historyId) {
            return [];
          }
          return [
            {
              id: historyId,
              decision:
                typeof history.decision === "string" ? history.decision : null,
              reason:
                typeof history.reason === "string" ? history.reason : null,
              created_at:
                typeof history.created_at === "string"
                  ? history.created_at
                  : null,
            },
          ];
        })
      : [],
  };
}

function normalizeMessageMemoryWriteDetail(
  value: unknown,
): MessageMemoryWriteDetail | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const candidate = value as Record<string, unknown>;
  const rawRun =
    candidate.run && typeof candidate.run === "object"
      ? (candidate.run as Record<string, unknown>)
      : null;
  const run =
    rawRun && typeof rawRun.id === "string" && rawRun.id.trim()
      ? {
          id: rawRun.id.trim(),
          status:
            typeof rawRun.status === "string" ? rawRun.status.trim() : null,
          extraction_model:
            typeof rawRun.extraction_model === "string"
              ? rawRun.extraction_model
              : null,
          consolidation_model:
            typeof rawRun.consolidation_model === "string"
              ? rawRun.consolidation_model
              : null,
          error: typeof rawRun.error === "string" ? rawRun.error : null,
          started_at:
            typeof rawRun.started_at === "string" ? rawRun.started_at : null,
          completed_at:
            typeof rawRun.completed_at === "string"
              ? rawRun.completed_at
              : null,
          created_at:
            typeof rawRun.created_at === "string" ? rawRun.created_at : null,
          metadata_json:
            rawRun.metadata_json && typeof rawRun.metadata_json === "object"
              ? (rawRun.metadata_json as Record<string, unknown>)
              : {},
        }
      : null;
  const items = Array.isArray(candidate.items)
    ? candidate.items.flatMap((item) => {
        if (!item || typeof item !== "object") {
          return [];
        }
        const rawItem = item as Record<string, unknown>;
        const id = typeof rawItem.id === "string" ? rawItem.id.trim() : "";
        const candidateText =
          typeof rawItem.candidate_text === "string"
            ? rawItem.candidate_text.trim()
            : "";
        if (!id || !candidateText) {
          return [];
        }
        return [
          {
            id,
            subject_memory_id:
              typeof rawItem.subject_memory_id === "string"
                ? rawItem.subject_memory_id
                : null,
            candidate_text: candidateText,
            category:
              typeof rawItem.category === "string" ? rawItem.category : "",
            proposed_memory_kind:
              typeof rawItem.proposed_memory_kind === "string"
                ? rawItem.proposed_memory_kind
                : null,
            importance:
              typeof rawItem.importance === "number" ? rawItem.importance : 0,
            decision:
              typeof rawItem.decision === "string" ? rawItem.decision : null,
            target_memory_id:
              typeof rawItem.target_memory_id === "string"
                ? rawItem.target_memory_id
                : null,
            predecessor_memory_id:
              typeof rawItem.predecessor_memory_id === "string"
                ? rawItem.predecessor_memory_id
                : null,
            reason:
              typeof rawItem.reason === "string" ? rawItem.reason : null,
            metadata_json:
              rawItem.metadata_json && typeof rawItem.metadata_json === "object"
                ? (rawItem.metadata_json as Record<string, unknown>)
                : {},
            created_at:
              typeof rawItem.created_at === "string"
                ? rawItem.created_at
                : null,
          },
        ];
      })
    : [];
  if (!run && !items.length) {
    return null;
  }
  return { run, items };
}

function shouldAnimateAssistantMessage(message: Message): boolean {
  const hasSources = (message.sources?.length ?? 0) > 0;
  const hasRetrievalTrace =
    Boolean(message.retrievalTrace) &&
    ((message.retrievalTrace?.memories.length ?? 0) > 0 ||
      (message.retrievalTrace?.knowledge_chunks.length ?? 0) > 0 ||
      (message.retrievalTrace?.linked_file_chunks.length ?? 0) > 0);
  const hasMemoryWrites =
    (message.memory_write_preview?.items.length ?? 0) > 0 ||
    (message.extracted_facts?.length ?? 0) > 0;
  const hasReasoning = Boolean(message.reasoningContent?.trim());

  return !(hasSources || hasRetrievalTrace || hasMemoryWrites || hasReasoning);
}

function hasSupplementalAssistantData(message: Message | null | undefined): boolean {
  if (!message || message.role !== "assistant") {
    return false;
  }

  const extractionStatus = message.memory_extraction_status?.trim() || null;
  return (
    (message.sources?.length ?? 0) > 0 ||
    Boolean(message.retrievalTrace) ||
    (message.memory_write_preview?.items.length ?? 0) > 0 ||
    (message.extracted_facts?.length ?? 0) > 0 ||
    Boolean(message.memories_extracted?.trim()) ||
    (Boolean(extractionStatus) && extractionStatus !== "pending")
  );
}

function shouldHydrateAfterAssistantMetadataPatch(metadata: unknown): boolean {
  if (!metadata || typeof metadata !== "object") {
    return false;
  }

  const candidate = metadata as Record<string, unknown>;
  if (
    candidate.memory_write_preview &&
    typeof candidate.memory_write_preview === "object"
  ) {
    return true;
  }
  if (Array.isArray(candidate.extracted_facts) && candidate.extracted_facts.length > 0) {
    return true;
  }
  if (
    typeof candidate.memories_extracted === "string" &&
    candidate.memories_extracted.trim()
  ) {
    return true;
  }
  if (
    typeof candidate.memory_extraction_status === "string" &&
    candidate.memory_extraction_status.trim() &&
    candidate.memory_extraction_status.trim() !== "pending"
  ) {
    return true;
  }
  return false;
}

function shouldReuseLiveTranscriptMessage(
  role: Message["role"],
  existingContent: string,
  nextContent: string,
): boolean {
  if (role !== "user") {
    return false;
  }
  const current = existingContent.trim();
  const incoming = nextContent.trim();
  if (!current || !incoming) {
    return false;
  }
  return incoming.startsWith(current) || current.startsWith(incoming);
}

function findCollapsibleTrailingUserMessage(
  messages: Message[],
  nextContent: string,
): Message | null {
  let trailingStart = messages.length;
  while (trailingStart > 0 && messages[trailingStart - 1]?.role === "user") {
    trailingStart -= 1;
  }
  if (trailingStart === messages.length) {
    return null;
  }
  const trailingUsers = messages.slice(trailingStart);
  if (
    trailingUsers.some(
      (message) =>
        message.role !== "user" ||
        !shouldReuseLiveTranscriptMessage("user", message.content, nextContent),
    )
  ) {
    return null;
  }
  return trailingUsers[trailingUsers.length - 1] ?? null;
}

export function ChatInterface({
  conversationId,
  projectId,
  isConversationPending = false,
  onConversationActivity,
  onConversationLoaded,
}: ChatInterfaceProps) {
  const t = useTranslations("console-chat");
  const [messages, setMessages] = useState<Message[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [voiceNotice, setVoiceNotice] = useState<string | null>(null);
  const [autoReadEnabled, setAutoReadEnabled] = useState(false);
  const [projectDefaultMode, setProjectDefaultMode] =
    useState<ChatMode>("standard");
  const [pipelineItems, setPipelineItems] = useState<PipelineConfigItem[]>([]);
  const [catalogItems, setCatalogItems] = useState<CatalogModelItem[]>([]);
  const [conversationModeOverrides, setConversationModeOverrides] = useState<
    Record<string, ChatMode>
  >({});
  const [sessionModeOverride, setSessionModeOverride] =
    useState<ChatMode | null>(null);
  const [voiceSessionState, setVoiceSessionState] = useState("idle");
  const [liveDictationText, setLiveDictationText] = useState("");
  const [isLiveDictating, setIsLiveDictating] = useState(false);
  const [isStreamingActive, setIsStreamingActive] = useState(false);
  const [uiMode, setUiMode] = useState<"user" | "debug">("user");
  const [inspectorState, setInspectorState] = useState<InspectorState>({
    open: false,
    tab: "context",
    messageId: null,
    section: null,
  });
  const [messageInspectorOverrides, setMessageInspectorOverrides] = useState<
    Record<string, MessageInspectorOverride>
  >({});
  const [memoryDetails, setMemoryDetails] = useState<
    Record<string, InspectorMemoryRecord>
  >({});
  const [memoryStatuses, setMemoryStatuses] = useState<
    Record<string, "idle" | "loading" | "saving" | "deleting" | "promoting">
  >({});
  const [memoryWriteDetails, setMemoryWriteDetails] = useState<
    Record<string, MessageMemoryWriteDetail | null>
  >({});
  const [memoryWriteStatuses, setMemoryWriteStatuses] = useState<
    Record<string, "idle" | "loading">
  >({});
  const [viewportWidth, setViewportWidth] = useState(1440);
  const [pendingAutoRead, setPendingAutoRead] = useState<{
    messageId: string;
    audioBase64?: string | null;
  } | null>(null);

  const messageListRef = useRef<ChatMessageListHandle>(null);
  const messagesRef = useRef<Message[]>([]);
  const pendingAssistantMetadataRef = useRef<Record<string, unknown>>({});
  const activeConversationIdRef = useRef<string | null>(conversationId ?? null);
  const scheduledConversationSyncsRef = useRef<number[]>([]);
  const scheduleConversationHydrationSyncRef = useRef<
    (
      targetConversationId: string,
      assistantMessageId?: string | null,
      options?: {
        delayMs?: number;
        force?: boolean;
      },
    ) => void
  >(() => undefined);
  const pendingRealtimeTurnPersistenceRef = useRef<
    Array<{
      userRuntimeId: string | null;
      assistantRuntimeId: string | null;
    }>
  >([]);
  const abortControllerRef = useRef<AbortController | null>(null);
  const streamAbortReasonRef = useRef<
    "user" | "no_first_event" | "idle" | null
  >(null);
  const requestGenerationRef = useRef(0);
  const runtimeMessageCounterRef = useRef(0);
  const memoryExtractionSyncInFlightRef = useRef(false);
  const liveTurnIdsRef = useRef<{
    userId: string | null;
    assistantId: string | null;
  }>({
    userId: null,
    assistantId: null,
  });
  const voiceContextRef = useRef<{
    conversationId: string | null;
    projectId: string | null;
    chatMode: ChatMode;
  }>({
    conversationId: conversationId ?? null,
    projectId: projectId ?? null,
    chatMode: projectDefaultMode,
  });

  const nextRuntimeMessageId = useCallback((prefix: string) => {
    runtimeMessageCounterRef.current += 1;
    return `${prefix}-${Date.now()}-${runtimeMessageCounterRef.current}`;
  }, []);
  const queueAutoRead = useCallback(
    (messageId: string, audioBase64?: string | null) => {
      setPendingAutoRead({ messageId, audioBase64 });
    },
    [],
  );
  const publishConversationPreview = useCallback(
    (previewText: string) => {
      if (!conversationId) {
        return;
      }
      onConversationActivity?.({
        conversationId,
        previewText,
      });
    },
    [conversationId, onConversationActivity],
  );
  const invalidateActiveRequest = useCallback(() => {
    requestGenerationRef.current += 1;
    streamAbortReasonRef.current = "user";
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    setIsTyping(false);
    setIsStreamingActive(false);
    setPendingAutoRead(null);
    messageListRef.current?.stopPlayback();
  }, []);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    activeConversationIdRef.current = conversationId ?? null;
  }, [conversationId]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const updateViewportWidth = () => {
      setViewportWidth(window.innerWidth);
    };

    updateViewportWidth();
    window.addEventListener("resize", updateViewportWidth);
    return () => window.removeEventListener("resize", updateViewportWidth);
  }, []);

  useEffect(() => {
    const pendingEntries = Object.entries(pendingAssistantMetadataRef.current);
    if (!pendingEntries.length || !messages.length) {
      return;
    }

    let changed = false;
    const nextMessages = messages.map((message) => {
      const pendingMetadata = pendingAssistantMetadataRef.current[message.id];
      if (!pendingMetadata) {
        return message;
      }

      changed = true;
      delete pendingAssistantMetadataRef.current[message.id];
      return mergeAssistantMetadataPatch(message, pendingMetadata);
    });

    if (changed) {
      setMessages(nextMessages);
    }
  }, [messages]);

  useEffect(() => {
    invalidateActiveRequest();
    liveTurnIdsRef.current = { userId: null, assistantId: null };
    pendingRealtimeTurnPersistenceRef.current = [];
    setInspectorState({
      open: false,
      tab: "context",
      messageId: null,
      section: null,
    });
    setUiMode("user");
    setMessageInspectorOverrides({});
    setMemoryDetails({});
    setMemoryStatuses({});
    setMemoryWriteDetails({});
    setMemoryWriteStatuses({});
    const pendingSyncs = scheduledConversationSyncsRef.current;
    scheduledConversationSyncsRef.current = [];
    pendingSyncs.forEach((timeoutId) => window.clearTimeout(timeoutId));
  }, [conversationId, invalidateActiveRequest, projectId]);

  useEffect(() => {
    if (!pendingAutoRead) {
      return;
    }

    const targetMessage = messages.find(
      (message) => message.id === pendingAutoRead.messageId,
    );
    if (!targetMessage || targetMessage.isStreaming) {
      return;
    }

    const hasPlayableContent = Boolean(
      targetMessage.content.trim() ||
      targetMessage.audioBase64 ||
      pendingAutoRead.audioBase64,
    );
    if (!hasPlayableContent) {
      return;
    }

    if (pendingAutoRead.audioBase64) {
      messageListRef.current?.playReadAloud(
        pendingAutoRead.messageId,
        pendingAutoRead.audioBase64,
      );
    } else {
      messageListRef.current?.playReadAloud(pendingAutoRead.messageId);
    }
    setPendingAutoRead((current) =>
      current?.messageId === pendingAutoRead.messageId ? null : current,
    );
  }, [messages, pendingAutoRead]);

  useEffect(() => {
    if (!projectId) {
      setProjectDefaultMode("standard");
      setPipelineItems([]);
      setCatalogItems([]);
      setConversationModeOverrides({});
      return;
    }

    let cancelled = false;
    void Promise.all([
      apiGet<ProjectChatSettings>(`/api/v1/projects/${projectId}`),
      apiGet<PipelineResponse>(`/api/v1/pipeline?project_id=${projectId}`),
      apiGet<CatalogModelItem[]>("/api/v1/models/catalog"),
    ])
      .then(([projectData, pipelineData, catalogData]) => {
        if (cancelled) {
          return;
        }
        const nextPipeline = Array.isArray(pipelineData.items)
          ? pipelineData.items
          : [];
        const nextCatalog = Array.isArray(catalogData) ? catalogData : [];
        const llmModelId = getPipelineModelId(
          nextPipeline,
          "llm",
          "qwen3.5-plus",
        );
        const syntheticSupported = modelSupportsCapability(
          nextCatalog,
          llmModelId,
          "vision",
        );
        const nextDefault =
          projectData.default_chat_mode === "synthetic_realtime" &&
          !syntheticSupported
            ? "standard"
            : projectData.default_chat_mode || "standard";
        setPipelineItems(nextPipeline);
        setCatalogItems(nextCatalog);
        setProjectDefaultMode(nextDefault);
        if (!syntheticSupported) {
          setConversationModeOverrides((prev) => {
            let changed = false;
            const next: Record<string, ChatMode> = {};
            for (const [key, value] of Object.entries(prev)) {
              if (value === "synthetic_realtime") {
                changed = true;
                continue;
              }
              next[key] = value;
            }
            return changed ? next : prev;
          });
        }
      })
      .catch(() => {
        if (cancelled) {
          return;
        }
        setProjectDefaultMode("standard");
        setPipelineItems([]);
        setCatalogItems([]);
        setConversationModeOverrides({});
      });

    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // Load messages when conversationId changes
  useEffect(() => {
    setVoiceNotice(null);
    messageListRef.current?.stopPlayback();
    if (!conversationId) {
      setMessages([]);
      return;
    }

    let cancelled = false;
    setLoadingMessages(true);

    apiGet<ApiMessage[]>(
      `/api/v1/chat/conversations/${conversationId}/messages`,
    )
      .then((data) => {
        if (!cancelled) {
          const list = Array.isArray(data) ? data : [];
          setMessages(list.map(toMessage));
          onConversationLoaded?.({
            conversationId,
            messages: list,
          });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setMessages([]);
          onConversationLoaded?.({
            conversationId,
            messages: [],
          });
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingMessages(false);
      });

    return () => {
      cancelled = true;
    };
  }, [conversationId, onConversationLoaded]);

  useEffect(() => {
    if (!conversationId) {
      return;
    }

    let eventSource: EventSource | null = null;
    let retryTimeout: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      const apiBase = getApiHttpBaseUrl();
      eventSource = new EventSource(
        `${apiBase}/api/v1/chat/conversations/${conversationId}/events`,
        { withCredentials: true },
      );

      eventSource.addEventListener("assistant_message_metadata", (event) => {
        try {
          const payload = JSON.parse(event.data) as {
            id?: string;
            metadata_json?: unknown;
          };
          if (!payload.id) {
            return;
          }
          pendingAssistantMetadataRef.current[payload.id] =
            payload.metadata_json ?? {};
          let matchedMessage = false;
          setMessages((prev) =>
            prev.map((message) => {
              if (message.id !== payload.id) {
                return message;
              }
              matchedMessage = true;
              delete pendingAssistantMetadataRef.current[payload.id];
              return mergeAssistantMetadataPatch(
                message,
                payload.metadata_json,
              );
            }),
          );
          if (
            !matchedMessage ||
            shouldHydrateAfterAssistantMetadataPatch(payload.metadata_json)
          ) {
            scheduleConversationHydrationSyncRef.current(conversationId, payload.id, {
              delayMs: matchedMessage ? 120 : 300,
              force: true,
            });
          }
        } catch {
          // Ignore malformed event payloads.
        }
      });

      eventSource.onerror = () => {
        eventSource?.close();
        eventSource = null;
        retryTimeout = setTimeout(connect, 5000);
      };
    };

    connect();

    return () => {
      eventSource?.close();
      if (retryTimeout) {
        clearTimeout(retryTimeout);
      }
    };
  }, [conversationId]);

  const syncConversationMessages = useCallback(
    async (
      targetConversationId: string,
      options?: {
        fallbackAssistantMessage?: Message | null;
      },
    ) => {
      try {
        const data = await apiGet<ApiMessage[]>(
          `/api/v1/chat/conversations/${targetConversationId}/messages`,
        );
        const list = Array.isArray(data) ? data : [];
        const syncedMessages = list.map(toMessage);
        const lastSyncedMessage = syncedMessages[syncedMessages.length - 1];
        const fallbackAssistantMessage = options?.fallbackAssistantMessage;
        const nextMessages =
          fallbackAssistantMessage && lastSyncedMessage?.role === "user"
            ? [...syncedMessages, fallbackAssistantMessage]
            : syncedMessages;
        setMessages(nextMessages);
        onConversationLoaded?.({
          conversationId: targetConversationId,
          messages: list,
        });
      } catch {
        // Keep current optimistic UI if refresh fails.
      }
    },
    [onConversationLoaded],
  );

  const scheduleConversationHydrationSync = useCallback(
    (
      targetConversationId: string,
      assistantMessageId?: string | null,
      options?: {
        delayMs?: number;
        force?: boolean;
      },
    ) => {
      if (typeof window === "undefined") {
        return;
      }

      const delayMs = options?.delayMs ?? 900;
      const force = options?.force ?? false;
      const timeoutId = window.setTimeout(() => {
        scheduledConversationSyncsRef.current =
          scheduledConversationSyncsRef.current.filter((id) => id !== timeoutId);

        if (activeConversationIdRef.current !== targetConversationId) {
          return;
        }

        if (assistantMessageId) {
          const assistantMessage = messagesRef.current.find(
            (message) => message.id === assistantMessageId,
          );
          if (!force && hasSupplementalAssistantData(assistantMessage)) {
            return;
          }
        }

        void syncConversationMessages(targetConversationId);
      }, delayMs);

      scheduledConversationSyncsRef.current.push(timeoutId);
    },
    [syncConversationMessages],
  );
  scheduleConversationHydrationSyncRef.current = scheduleConversationHydrationSync;

  useEffect(() => {
    if (!conversationId) {
      return;
    }

    const hasPendingMemoryExtraction = messages.some(
      (message) =>
        message.role === "assistant" &&
        !message.isStreaming &&
        message.memory_extraction_status === "pending",
    );
    if (!hasPendingMemoryExtraction) {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      if (memoryExtractionSyncInFlightRef.current) {
        return;
      }
      memoryExtractionSyncInFlightRef.current = true;
      void syncConversationMessages(conversationId).finally(() => {
        memoryExtractionSyncInFlightRef.current = false;
      });
    }, 900);

    return () => {
      clearTimeout(timeoutId);
    };
  }, [conversationId, messages, syncConversationMessages]);

  const updateMemoryStatus = useCallback(
    (
      memoryId: string,
      status: "idle" | "loading" | "saving" | "deleting" | "promoting",
    ) => {
      setMemoryStatuses((prev) => ({
        ...prev,
        [memoryId]: status,
      }));
    },
    [],
  );

  const applyInspectorOverride = useCallback(
    (
      messageId: string,
      memoryId: string,
      patch: Partial<MessageInspectorOverride>,
    ) => {
      const key = getMessageInspectorOverrideKey(messageId, memoryId);
      setMessageInspectorOverrides((prev) => ({
        ...prev,
        [key]: {
          ...(prev[key] ?? {}),
          ...patch,
          targetMemoryId: memoryId,
        },
      }));
    },
    [],
  );

  const ensureMemoryDetail = useCallback(
    async (memoryId: string) => {
      if (!memoryId || memoryDetails[memoryId] || memoryStatuses[memoryId] === "loading") {
        return;
      }

      updateMemoryStatus(memoryId, "loading");
      try {
        const response = await apiGet<InspectorMemoryRecord | { node?: unknown }>(
          `/api/v1/memory/${memoryId}`,
        );
        const record =
          normalizeMemoryRecord(response) ||
          normalizeMemoryRecord((response as { node?: unknown }).node);
        if (record) {
          setMemoryDetails((prev) => ({
            ...prev,
            [memoryId]: record,
          }));
        }
      } catch {
        setVoiceNotice(t("inspector.memory.actionFailed"));
      } finally {
        updateMemoryStatus(memoryId, "idle");
      }
    },
    [memoryDetails, memoryStatuses, t, updateMemoryStatus],
  );

  const ensureMemoryWriteDetail = useCallback(
    async (messageId: string) => {
      if (!messageId || memoryWriteDetails[messageId] || memoryWriteStatuses[messageId] === "loading") {
        return;
      }

      setMemoryWriteStatuses((prev) => ({
        ...prev,
        [messageId]: "loading",
      }));
      try {
        const response = await apiGet<MessageMemoryWriteDetail>(
          `/api/v1/chat/messages/${messageId}/memory-write`,
        );
        setMemoryWriteDetails((prev) => ({
          ...prev,
          [messageId]: normalizeMessageMemoryWriteDetail(response),
        }));
      } catch {
        setVoiceNotice(t("inspector.memory.actionFailed"));
      } finally {
        setMemoryWriteStatuses((prev) => ({
          ...prev,
          [messageId]: "idle",
        }));
      }
    },
    [memoryWriteDetails, memoryWriteStatuses, t],
  );

  const handleUpdateMemory = useCallback(
    async ({
      messageId,
      memoryId,
      content,
    }: {
      messageId: string;
      memoryId: string;
      content: string;
    }) => {
      updateMemoryStatus(memoryId, "saving");
      try {
        const response = await apiPatch<InspectorMemoryRecord>(
          `/api/v1/memory/${memoryId}`,
          { content },
        );
        const record =
          normalizeMemoryRecord(response) ?? {
            id: memoryId,
            content,
            category: memoryDetails[memoryId]?.category || "",
            type: memoryDetails[memoryId]?.type || "permanent",
            metadata_json: memoryDetails[memoryId]?.metadata_json || {},
          };
        setMemoryDetails((prev) => ({
          ...prev,
          [memoryId]: record,
        }));
        applyInspectorOverride(messageId, memoryId, {
          fact: record.content,
        });
      } catch {
        setVoiceNotice(t("inspector.memory.actionFailed"));
      } finally {
        updateMemoryStatus(memoryId, "idle");
      }
    },
    [applyInspectorOverride, memoryDetails, t, updateMemoryStatus],
  );

  const handleDeleteMemory = useCallback(
    async ({
      messageId,
      memoryId,
    }: {
      messageId: string;
      memoryId: string;
    }) => {
      updateMemoryStatus(memoryId, "deleting");
      try {
        await apiDelete(`/api/v1/memory/${memoryId}`);
        applyInspectorOverride(messageId, memoryId, { hidden: true });
        setMemoryDetails((prev) => {
          if (!(memoryId in prev)) {
            return prev;
          }
          const next = { ...prev };
          delete next[memoryId];
          return next;
        });
      } catch {
        setVoiceNotice(t("inspector.memory.actionFailed"));
      } finally {
        updateMemoryStatus(memoryId, "idle");
      }
    },
    [applyInspectorOverride, t, updateMemoryStatus],
  );

  const handlePromoteMemory = useCallback(
    async ({
      messageId,
      memoryId,
    }: {
      messageId: string;
      memoryId: string;
    }) => {
      updateMemoryStatus(memoryId, "promoting");
      try {
        const response = await apiPost<InspectorMemoryRecord>(
          `/api/v1/memory/${memoryId}/promote`,
        );
        const record =
          normalizeMemoryRecord(response) ?? {
            id: memoryId,
            content: memoryDetails[memoryId]?.content || "",
            category: memoryDetails[memoryId]?.category || "",
            type: "permanent",
            metadata_json: memoryDetails[memoryId]?.metadata_json || {},
          };
        setMemoryDetails((prev) => ({
          ...prev,
          [memoryId]: {
            ...record,
            type: "permanent",
          },
        }));
        applyInspectorOverride(messageId, memoryId, {
          memoryType: "permanent",
          status: "permanent",
        });
      } catch {
        setVoiceNotice(t("inspector.memory.actionFailed"));
      } finally {
        updateMemoryStatus(memoryId, "idle");
      }
    },
    [applyInspectorOverride, memoryDetails, t, updateMemoryStatus],
  );

  const openInspector = useCallback(
    ({
      tab,
      messageId,
      section,
    }: {
      tab: InspectorState["tab"];
      messageId: string;
      section?: InspectorState["section"];
    }) => {
      setInspectorState({
        open: true,
        tab,
        messageId,
        section: section ?? null,
      });
    },
    [],
  );

  const handleSend = useCallback(
    async (
      content: string,
      options: {
        enableThinking?: boolean | null;
        enableSearch?: boolean | null;
        imageFile?: File | null;
      },
    ) => {
      if (!conversationId || isTyping || isStreamingActive) {
        return;
      }

      const requestGeneration = ++requestGenerationRef.current;
      const isCurrentRequest = () =>
        requestGenerationRef.current === requestGeneration;

      const imageFile = options.imageFile ?? null;
      const enableThinking = options.enableThinking ?? null;
      const enableSearch = options.enableSearch ?? null;

      if (imageFile) {
        const submittedText = content || t("imageDefaultPrompt");
        const userMessage: Message = {
          id: nextRuntimeMessageId("img-u"),
          role: "user",
          content: submittedText,
        };

        setMessages((prev) => [...prev, userMessage]);
        setIsTyping(true);
        setVoiceNotice(null);
        publishConversationPreview(submittedText);

        try {
          const formData = new FormData();
          formData.append("image", imageFile, imageFile.name);
          if (content) {
            formData.append("prompt", content);
          }
          if (enableThinking === true) {
            formData.append("enable_thinking", "true");
          } else if (enableThinking === false) {
            formData.append("enable_thinking", "false");
          }
          if (enableSearch === true) {
            formData.append("enable_search", "true");
          } else if (enableSearch === false) {
            formData.append("enable_search", "false");
          }

          const response = await apiPostFormData<ImageMessageResponse>(
            `/api/v1/chat/conversations/${conversationId}/image`,
            formData,
          );
          if (!isCurrentRequest()) {
            return;
          }

          const baseMessage = toMessage(response.message);
          const assistantMessage: Message = {
            ...baseMessage,
            id: response.message?.id || nextRuntimeMessageId("img-a"),
            audioBase64: response.audio_response,
            animateOnMount: shouldAnimateAssistantMessage(baseMessage),
            isStreaming: false,
          };
          setMessages((prev) => [...prev, assistantMessage]);
          publishConversationPreview(assistantMessage.content);
          if (autoReadEnabled && response.audio_response) {
            queueAutoRead(assistantMessage.id, response.audio_response);
          }
        } catch (error) {
          if (!isCurrentRequest()) {
            return;
          }
          const errorContent = isApiRequestError(error)
            ? getApiErrorMessage(error, t)
            : t("errors.imageUploadFailed");
          setMessages((prev) => [
            ...prev,
            {
              id: nextRuntimeMessageId("img-err"),
              role: "assistant",
              content: errorContent,
            },
          ]);
          publishConversationPreview(errorContent);
        } finally {
          if (isCurrentRequest()) {
            setIsTyping(false);
          }
        }
        return;
      }

      if (!content) {
        return;
      }

      const userMessage: Message = {
        id: nextRuntimeMessageId("u"),
        role: "user",
        content,
      };

      setMessages((prev) => [...prev, userMessage]);
      setIsTyping(true);
      setVoiceNotice(null);
      publishConversationPreview(content);

      const streamBody = {
        content,
        enable_thinking:
          enableThinking === true
            ? true
            : enableThinking === false
              ? false
              : undefined,
        enable_search:
          enableSearch === true
            ? true
            : enableSearch === false
              ? false
              : undefined,
      };

      const tempAssistantId = nextRuntimeMessageId("stream-a");
      let streamStarted = false;
      let finalizedAssistantId: string | null = null;
      let sawStreamEvent = false;
      let watchdogTimeout: ReturnType<typeof setTimeout> | null = null;
      const clearWatchdog = () => {
        if (watchdogTimeout) {
          clearTimeout(watchdogTimeout);
          watchdogTimeout = null;
        }
      };
      const updateStreamingAssistant = (
        updater: (current: Message | null) => Message,
      ) => {
        setMessages((prev) => {
          const index = prev.findIndex(
            (message) => message.id === tempAssistantId,
          );
          const current = index >= 0 ? prev[index] : null;
          const nextMessage = updater(current);
          if (index === -1) {
            return [...prev, nextMessage];
          }
          const next = prev.slice();
          next[index] = nextMessage;
          return next;
        });
      };
      const finalizeStreamingAssistant = (
        final: Omit<Message, "role"> & { role?: "assistant" },
      ) => {
        setMessages((prev) => {
          const index = prev.findIndex(
            (message) => message.id === tempAssistantId,
          );
          const current = index >= 0 ? prev[index] : null;
          let nextMessage: Message = {
            id: final.id,
            role: "assistant",
            content: final.content,
            reasoningContent: final.reasoningContent ?? null,
            sources:
              final.sources !== undefined ? final.sources : current?.sources,
            retrievalTrace:
              final.retrievalTrace !== undefined
                ? final.retrievalTrace
                : (current?.retrievalTrace ?? null),
            audioBase64: final.audioBase64 ?? current?.audioBase64 ?? null,
            memories_extracted:
              final.memories_extracted ?? current?.memories_extracted,
            memory_write_preview:
              final.memory_write_preview !== undefined
                ? final.memory_write_preview
                : (current?.memory_write_preview ?? null),
            extracted_facts:
              final.extracted_facts !== undefined
                ? final.extracted_facts
                : current?.extracted_facts,
            memory_extraction_status:
              final.memory_extraction_status ??
              current?.memory_extraction_status ??
              null,
            memory_extraction_attempts:
              final.memory_extraction_attempts ??
              current?.memory_extraction_attempts ??
              null,
            memory_extraction_error:
              final.memory_extraction_error ??
              current?.memory_extraction_error ??
              null,
            metadataJson: current?.metadataJson ?? null,
            animateOnMount:
              final.animateOnMount ?? current?.animateOnMount ?? false,
            isStreaming: final.isStreaming,
          };
          const pendingMetadata = pendingAssistantMetadataRef.current[final.id];
          if (pendingMetadata) {
            delete pendingAssistantMetadataRef.current[final.id];
            nextMessage = mergeAssistantMetadataPatch(nextMessage, pendingMetadata);
          }
          if (index === -1) {
            return [...prev.filter((m) => m.id !== nextMessage.id), nextMessage];
          }
          // Remove any pre-existing message with the same final ID to
          // prevent React duplicate-key warnings when the server-assigned
          // ID already appears elsewhere in the array.
          const next = prev
            .filter(
              (m, i) => i === index || m.id !== nextMessage.id,
            );
          const adjustedIndex = next.findIndex(
            (m) => m.id === tempAssistantId,
          );
          if (adjustedIndex >= 0) {
            next[adjustedIndex] = nextMessage;
          }
          return next;
        });
      };

      try {
        const abortController = new AbortController();
        abortControllerRef.current = abortController;
        streamAbortReasonRef.current = null;
        setIsStreamingActive(true);
        const armWatchdog = () => {
          clearWatchdog();
          watchdogTimeout = setTimeout(
            () => {
              streamAbortReasonRef.current = sawStreamEvent
                ? "idle"
                : "no_first_event";
              abortController.abort();
            },
            sawStreamEvent ? 45000 : 15000,
          );
        };

        const assistantPlaceholder: Message = {
          id: tempAssistantId,
          role: "assistant",
          content: "",
          isStreaming: true,
        };
        setMessages((prev) => [...prev, assistantPlaceholder]);
        setIsTyping(false);
        streamStarted = true;
        armWatchdog();

        for await (const event of apiStream(
          `/api/v1/chat/conversations/${conversationId}/stream`,
          streamBody,
          abortController.signal,
        )) {
          if (!isCurrentRequest()) {
            break;
          }
          sawStreamEvent = true;
          armWatchdog();
          if (event.event === "token") {
            const snapshot =
              typeof event.data.snapshot === "string"
                ? event.data.snapshot
                : null;
            const delta =
              typeof event.data.content === "string" ? event.data.content : "";
            updateStreamingAssistant((current) => ({
              id: tempAssistantId,
              role: "assistant",
              content: snapshot ?? normalizeStreamingMarkdown(
                (current?.content ?? "") + delta,
              ),
              reasoningContent: current?.reasoningContent ?? null,
              sources: current?.sources,
              retrievalTrace: current?.retrievalTrace ?? null,
              audioBase64: current?.audioBase64 ?? null,
              memories_extracted: current?.memories_extracted,
              memory_write_preview: current?.memory_write_preview ?? null,
              extracted_facts: current?.extracted_facts,
              memory_extraction_status:
                current?.memory_extraction_status ?? null,
              memory_extraction_attempts:
                current?.memory_extraction_attempts ?? null,
              memory_extraction_error: current?.memory_extraction_error ?? null,
              metadataJson: current?.metadataJson ?? null,
              animateOnMount: current?.animateOnMount ?? false,
              isStreaming: true,
            }));
          } else if (event.event === "reasoning") {
            const snapshot =
              typeof event.data.snapshot === "string"
                ? event.data.snapshot
                : null;
            const delta =
              typeof event.data.content === "string" ? event.data.content : "";
            updateStreamingAssistant((current) => ({
              id: tempAssistantId,
              role: "assistant",
              content: current?.content ?? "",
              reasoningContent: snapshot ?? normalizeStreamingMarkdown(
                (current?.reasoningContent ?? "") + delta,
              ),
              sources: current?.sources,
              retrievalTrace: current?.retrievalTrace ?? null,
              audioBase64: current?.audioBase64 ?? null,
              memories_extracted: current?.memories_extracted,
              memory_write_preview: current?.memory_write_preview ?? null,
              extracted_facts: current?.extracted_facts,
              memory_extraction_status:
                current?.memory_extraction_status ?? null,
              memory_extraction_attempts:
                current?.memory_extraction_attempts ?? null,
              memory_extraction_error: current?.memory_extraction_error ?? null,
              metadataJson: current?.metadataJson ?? null,
              animateOnMount: current?.animateOnMount ?? false,
              isStreaming: true,
            }));
          } else if (event.event === "message_done") {
            const finalId = (event.data.id as string) || tempAssistantId;
            const finalContent =
              typeof event.data.content === "string" ? event.data.content : "";
            const finalReasoning =
              typeof event.data.reasoning_content === "string"
                ? event.data.reasoning_content
                : null;
            const hasMemoriesExtracted = Object.prototype.hasOwnProperty.call(
              event.data,
              "memories_extracted",
            );
            const memoriesExtracted = hasMemoriesExtracted
              ? (event.data.memories_extracted as string | undefined)
              : undefined;
            const hasSources = Object.prototype.hasOwnProperty.call(
              event.data,
              "sources",
            );
            const sources = hasSources
              ? normalizeSearchSources(event.data.sources)
              : undefined;
            const hasRetrievalTrace = Object.prototype.hasOwnProperty.call(
              event.data,
              "retrieval_trace",
            );
            const retrievalTrace = hasRetrievalTrace
              ? normalizeRetrievalTrace(event.data.retrieval_trace)
              : undefined;
            const hasMemoryWritePreview = Object.prototype.hasOwnProperty.call(
              event.data,
              "memory_write_preview",
            );
            const memoryWritePreview = hasMemoryWritePreview
              ? toMessage({
                  id: finalId,
                  conversation_id: conversationId,
                  role: "assistant",
                  content: finalContent,
                  reasoning_content: finalReasoning,
                  metadata_json: {
                    memory_write_preview: event.data.memory_write_preview,
                  },
                  created_at: new Date().toISOString(),
                }).memory_write_preview
              : undefined;
            const hasExtractedFacts = Object.prototype.hasOwnProperty.call(
              event.data,
              "extracted_facts",
            );
            const extractedFacts = hasExtractedFacts
              ? toMessage({
                  id: finalId,
                  conversation_id: conversationId,
                  role: "assistant",
                  content: finalContent,
                  reasoning_content: finalReasoning,
                  metadata_json: {
                    extracted_facts: event.data.extracted_facts,
                  },
                  created_at: new Date().toISOString(),
                }).extracted_facts
              : undefined;
            const hasMemoryExtractionStatus = Object.prototype.hasOwnProperty.call(
              event.data,
              "memory_extraction_status",
            );
            const memoryExtractionStatus =
              hasMemoryExtractionStatus &&
              typeof event.data.memory_extraction_status === "string"
                ? event.data.memory_extraction_status
                : null;
            const hasMemoryExtractionAttempts = Object.prototype.hasOwnProperty.call(
              event.data,
              "memory_extraction_attempts",
            );
            const memoryExtractionAttempts =
              hasMemoryExtractionAttempts &&
              typeof event.data.memory_extraction_attempts === "number"
                ? event.data.memory_extraction_attempts
                : null;
            const hasMemoryExtractionError = Object.prototype.hasOwnProperty.call(
              event.data,
              "memory_extraction_error",
            );
            const memoryExtractionError =
              hasMemoryExtractionError &&
              typeof event.data.memory_extraction_error === "string"
                ? event.data.memory_extraction_error
                : null;
            finalizedAssistantId = finalId;
            finalizeStreamingAssistant({
              id: finalId,
              isStreaming: false,
              content: finalContent,
              reasoningContent: finalReasoning ?? null,
              memories_extracted: memoriesExtracted,
              memory_write_preview: memoryWritePreview,
              sources,
              retrievalTrace,
              extracted_facts: extractedFacts,
              memory_extraction_status: memoryExtractionStatus,
              memory_extraction_attempts: memoryExtractionAttempts,
              memory_extraction_error: memoryExtractionError,
            });
            publishConversationPreview(finalContent);
            scheduleConversationHydrationSync(conversationId, finalId);
          } else if (event.event === "error") {
            const errorMsg =
              (event.data.detail as string) ||
              (event.data.message as string) ||
              t("errors.streamError");
            finalizeStreamingAssistant({
              id: tempAssistantId,
              isStreaming: false,
              content: errorMsg,
              reasoningContent: null,
            });
            publishConversationPreview(errorMsg);
          }
        }
        clearWatchdog();
        if (!isCurrentRequest()) {
          return;
        }

        if (!finalizedAssistantId) {
          finalizedAssistantId = tempAssistantId;
          const fallbackContent =
            messagesRef.current.find((message) => message.id === tempAssistantId)
              ?.content ?? "";
          finalizeStreamingAssistant({
            id: tempAssistantId,
            isStreaming: false,
            content: fallbackContent,
            reasoningContent:
              messagesRef.current.find(
                (message) => message.id === tempAssistantId,
              )?.reasoningContent ?? null,
          });
          publishConversationPreview(fallbackContent);
        }

        if (autoReadEnabled) {
          queueAutoRead(finalizedAssistantId);
        }
      } catch (error) {
        const streamStatus =
          typeof error === "object" &&
          error !== null &&
          "status" in error &&
          typeof error.status === "number"
            ? error.status
            : null;
        const streamUnavailable =
          streamStatus === 404 || streamStatus === 405 || streamStatus === 501;
        const abortReason = streamAbortReasonRef.current;
        clearWatchdog();
        if (!isCurrentRequest()) {
          return;
        }

        if (error instanceof DOMException && error.name === "AbortError") {
          const currentStreamingMessage = messagesRef.current.find(
            (message) => message.id === tempAssistantId,
          );
          if (abortReason === "user") {
            const abortedContent = currentStreamingMessage?.content ?? "";
            finalizeStreamingAssistant({
              id: tempAssistantId,
              isStreaming: false,
              content: abortedContent,
              reasoningContent:
                currentStreamingMessage?.reasoningContent ?? null,
            });
            publishConversationPreview(abortedContent);
          } else {
            const fallbackAssistantMessage: Message = {
              id: tempAssistantId,
              role: "assistant",
              content:
                currentStreamingMessage?.content?.trim() ||
                t("errors.streamError"),
              reasoningContent:
                currentStreamingMessage?.reasoningContent ?? null,
              sources: currentStreamingMessage?.sources,
              retrievalTrace: currentStreamingMessage?.retrievalTrace ?? null,
              audioBase64: currentStreamingMessage?.audioBase64 ?? null,
              memories_extracted: currentStreamingMessage?.memories_extracted,
              memory_write_preview:
                currentStreamingMessage?.memory_write_preview ?? null,
              extracted_facts: currentStreamingMessage?.extracted_facts,
              memory_extraction_status:
                currentStreamingMessage?.memory_extraction_status ?? null,
              memory_extraction_attempts:
                currentStreamingMessage?.memory_extraction_attempts ?? null,
              memory_extraction_error:
                currentStreamingMessage?.memory_extraction_error ?? null,
              metadataJson: currentStreamingMessage?.metadataJson ?? null,
              animateOnMount: currentStreamingMessage?.animateOnMount ?? false,
              isStreaming: false,
            };
            finalizeStreamingAssistant({
              id: tempAssistantId,
              isStreaming: false,
              content: fallbackAssistantMessage.content,
              reasoningContent:
                fallbackAssistantMessage.reasoningContent ?? null,
            });
            publishConversationPreview(fallbackAssistantMessage.content);
            if (conversationId) {
              window.setTimeout(() => {
                if (isCurrentRequest()) {
                  void syncConversationMessages(conversationId, {
                    fallbackAssistantMessage,
                  });
                }
              }, 1500);
            }
          }
        } else if (streamUnavailable) {
          setMessages((prev) =>
            prev.filter((message) => message.id !== tempAssistantId),
          );
          try {
            setIsTyping(true);
            const response = await apiPost<ApiMessage>(
              `/api/v1/chat/conversations/${conversationId}/messages`,
              streamBody,
            );
            if (!isCurrentRequest()) {
              return;
            }
            const baseMessage = toMessage(response);
            const aiMessage: Message = {
              ...baseMessage,
              id: response.id || nextRuntimeMessageId("a"),
              animateOnMount: shouldAnimateAssistantMessage(baseMessage),
              isStreaming: false,
            };
            setMessages((prev) => [...prev, aiMessage]);
            publishConversationPreview(aiMessage.content);
            if (autoReadEnabled) {
              queueAutoRead(aiMessage.id);
            }
          } catch (fallbackError) {
            if (!isCurrentRequest()) {
              return;
            }
            const errorContent = isApiRequestError(fallbackError)
              ? getApiErrorMessage(fallbackError, t)
              : t("errors.generic");
            setMessages((prev) => [
              ...prev,
              {
                id: nextRuntimeMessageId("err"),
                role: "assistant",
                content: errorContent,
              },
            ]);
            publishConversationPreview(errorContent);
          } finally {
            if (isCurrentRequest()) {
              setIsTyping(false);
            }
          }
        } else if (streamStarted) {
          // Stream failed after starting — show error in the existing placeholder
          finalizeStreamingAssistant({
            id: tempAssistantId,
            isStreaming: false,
            content: t("errors.streamError"),
            reasoningContent: null,
          });
          publishConversationPreview(t("errors.streamError"));
        } else {
          // Stream never started — fall back to non-streaming apiPost
          try {
            setIsTyping(true);
            const response = await apiPost<ApiMessage>(
              `/api/v1/chat/conversations/${conversationId}/messages`,
              streamBody,
            );
            if (!isCurrentRequest()) {
              return;
            }
            const baseMessage = toMessage(response);
            const aiMessage: Message = {
              ...baseMessage,
              id: response.id || nextRuntimeMessageId("a"),
              animateOnMount: shouldAnimateAssistantMessage(baseMessage),
              isStreaming: false,
            };
            setMessages((prev) => [...prev, aiMessage]);
            publishConversationPreview(aiMessage.content);
            if (autoReadEnabled) {
              queueAutoRead(aiMessage.id);
            }
          } catch (fallbackError) {
            if (!isCurrentRequest()) {
              return;
            }
            const errorContent = isApiRequestError(fallbackError)
              ? getApiErrorMessage(fallbackError, t)
              : t("errors.generic");
            setMessages((prev) => [
              ...prev,
              {
                id: nextRuntimeMessageId("err"),
                role: "assistant",
                content: errorContent,
              },
            ]);
            publishConversationPreview(errorContent);
          } finally {
            if (isCurrentRequest()) {
              setIsTyping(false);
            }
          }
        }
      } finally {
        clearWatchdog();
        if (isCurrentRequest()) {
          abortControllerRef.current = null;
          streamAbortReasonRef.current = null;
          setIsStreamingActive(false);
        }
      }
    },
    [
      autoReadEnabled,
      conversationId,
      isStreamingActive,
      isTyping,
      nextRuntimeMessageId,
      publishConversationPreview,
      queueAutoRead,
      scheduleConversationHydrationSync,
      syncConversationMessages,
      t,
    ],
  );

  const handleLiveTranscriptUpdate = useCallback(
    ({ role, text, final, action = "upsert" }: LiveTranscriptUpdate) => {
      if (!conversationId) {
        return;
      }

      const slot = role === "user" ? "userId" : "assistantId";
      if (action === "discard") {
        const currentId = liveTurnIdsRef.current[slot];
        if (!currentId) {
          return;
        }
        setMessages((prev) =>
          prev.filter((message) => message.id !== currentId),
        );
        liveTurnIdsRef.current[slot] = null;
        return;
      }

      if (!text.trim()) {
        return;
      }
      const nextText = final ? text.trim() : text;

      let messageId = liveTurnIdsRef.current[slot];
      const collapsibleUserMessage =
        role === "user"
          ? findCollapsibleTrailingUserMessage(messagesRef.current, nextText)
          : null;
      if (collapsibleUserMessage) {
        messageId = collapsibleUserMessage.id;
        liveTurnIdsRef.current[slot] = messageId;
      }
      const existingMessage = messageId
        ? messagesRef.current.find((message) => message.id === messageId)
        : null;
      if (
        existingMessage &&
        !existingMessage.isStreaming &&
        !(final && existingMessage.content.trim() === nextText.trim()) &&
        !shouldReuseLiveTranscriptMessage(
          role,
          existingMessage.content,
          nextText,
        )
      ) {
        messageId = null;
      }
      if (!messageId) {
        messageId = nextRuntimeMessageId(role === "user" ? "rt-u" : "rt-a");
        liveTurnIdsRef.current[slot] = messageId;
      }

      setMessages((prev) => {
        const nextMessage: Message = {
          id: messageId,
          role,
          content: nextText,
          animateOnMount: false,
          isStreaming: !final,
        };
        if (role === "user" && collapsibleUserMessage) {
          let trailingStart = prev.length;
          while (
            trailingStart > 0 &&
            prev[trailingStart - 1]?.role === "user"
          ) {
            trailingStart -= 1;
          }
          return [...prev.slice(0, trailingStart), nextMessage];
        }
        const index = prev.findIndex((message) => message.id === messageId);
        if (index === -1) {
          return [...prev, nextMessage];
        }
        const next = prev.slice();
        next[index] = {
          ...next[index],
          content: nextText,
          isStreaming: !final,
        };
        return next;
      });

      if (role === "user" && final) {
        publishConversationPreview(nextText.trim());
      }
    },
    [conversationId, nextRuntimeMessageId, publishConversationPreview],
  );

  const handleRealtimeTurnComplete = useCallback(
    ({
      userText,
      assistantText,
    }: {
      userText: string;
      assistantText: string;
    }) => {
      if (!conversationId) {
        return;
      }
      const normalizedUserText = userText.trim();
      const normalizedAssistantText = assistantText.trim();

      if (normalizedAssistantText) {
        publishConversationPreview(normalizedAssistantText);
      } else if (normalizedUserText) {
        publishConversationPreview(normalizedUserText);
      }

      setMessages((prev) => {
        const next = prev.slice();

        if (normalizedUserText) {
          const userId = liveTurnIdsRef.current.userId;
          if (userId) {
            const index = next.findIndex((message) => message.id === userId);
            if (index >= 0) {
              next[index] = {
                ...next[index],
                content: normalizedUserText,
                isStreaming: false,
              };
            }
          }
          // Note: do NOT create a new message in the else branch —
          // handleLiveTranscriptUpdate already added it via onTranscriptUpdate.
          // Creating another one would cause duplicate user messages.
        }

        if (normalizedAssistantText) {
          const assistantId = liveTurnIdsRef.current.assistantId;
          if (assistantId) {
            const index = next.findIndex(
              (message) => message.id === assistantId,
            );
            if (index >= 0) {
              next[index] = {
                ...next[index],
                content: normalizedAssistantText,
                isStreaming: false,
              };
            }
          }
          // Note: do NOT create a new message in the else branch —
          // handleLiveTranscriptUpdate already added it via onTranscriptUpdate.
          // Creating another one would cause duplicate assistant messages.
        }

        return next;
      });
      if (normalizedUserText || normalizedAssistantText) {
        pendingRealtimeTurnPersistenceRef.current.push({
          userRuntimeId: liveTurnIdsRef.current.userId,
          assistantRuntimeId: liveTurnIdsRef.current.assistantId,
        });
      }
      liveTurnIdsRef.current = { userId: null, assistantId: null };
    },
    [conversationId, publishConversationPreview],
  );

  const handleRealtimeVoiceError = useCallback((message: string) => {
    setVoiceNotice(message);
    liveTurnIdsRef.current = { userId: null, assistantId: null };
  }, []);

  const handleRealtimeTurnPersisted = useCallback(
    ({ userMessage, assistantMessage }: PersistedRealtimeTurnPayload) => {
      const queuedTurn = pendingRealtimeTurnPersistenceRef.current.shift();
      if (!queuedTurn) {
        return;
      }

      setMessages((prev) => {
        const next = prev.slice();

        const applyPersistedMessage = (
          rawMessage: ApiMessage | undefined,
          runtimeId: string | null | undefined,
        ) => {
          if (!rawMessage) {
            return;
          }

          let persistedMessage: Message = {
            ...toMessage(rawMessage),
            animateOnMount: false,
            isStreaming: false,
          };
          const pendingMetadata =
            pendingAssistantMetadataRef.current[persistedMessage.id];
          if (pendingMetadata) {
            delete pendingAssistantMetadataRef.current[persistedMessage.id];
            persistedMessage = mergeAssistantMetadataPatch(
              persistedMessage,
              pendingMetadata,
            );
          }

          const existingPersistentIndex = next.findIndex(
            (message) => message.id === persistedMessage.id,
          );
          if (existingPersistentIndex >= 0) {
            next[existingPersistentIndex] = {
              ...next[existingPersistentIndex],
              ...persistedMessage,
              animateOnMount: false,
              isStreaming: false,
            };
            return;
          }

          if (runtimeId) {
            const runtimeIndex = next.findIndex(
              (message) => message.id === runtimeId,
            );
            if (runtimeIndex >= 0) {
              next[runtimeIndex] = {
                ...next[runtimeIndex],
                ...persistedMessage,
                animateOnMount: false,
                isStreaming: false,
              };
              return;
            }
          }

          next.push(persistedMessage);
        };

        applyPersistedMessage(
          userMessage as ApiMessage | undefined,
          queuedTurn?.userRuntimeId,
        );
        applyPersistedMessage(
          assistantMessage as ApiMessage | undefined,
          queuedTurn?.assistantRuntimeId,
        );
        return next;
      });
    },
    [],
  );

  const chatMode =
    conversationId && conversationModeOverrides[conversationId]
      ? conversationModeOverrides[conversationId]
      : (sessionModeOverride ?? projectDefaultMode);

  useEffect(() => {
    setLiveDictationText("");
    setIsLiveDictating(false);
  }, [conversationId, projectId]);

  useEffect(() => {
    setSessionModeOverride(null);
  }, [conversationId, projectId]);

  useEffect(() => {
    if (uiMode === "debug") {
      return;
    }
    setInspectorState((current) =>
      current.tab === "debug"
        ? {
            ...current,
            tab: "context",
            section: current.section === "raw" ? null : current.section,
          }
        : current,
    );
  }, [uiMode]);

  useEffect(() => {
    if (!inspectorState.messageId) {
      return;
    }
    if (messages.some((message) => message.id === inspectorState.messageId)) {
      return;
    }
    setInspectorState({
      open: false,
      tab: "context",
      messageId: null,
      section: null,
    });
  }, [inspectorState.messageId, messages]);

  const handleLiveDictationDraftChange = useCallback((text: string) => {
    setVoiceNotice(null);
    setLiveDictationText(text);
  }, []);

  useEffect(() => {
    if (!conversationId || chatMode === "standard") {
      setVoiceSessionState("idle");
    }
  }, [chatMode, conversationId]);

  useEffect(() => {
    const previous = voiceContextRef.current;
    const next = {
      conversationId: conversationId ?? null,
      projectId: projectId ?? null,
      chatMode,
    };
    const contextChanged =
      previous.conversationId !== next.conversationId ||
      previous.projectId !== next.projectId ||
      previous.chatMode !== next.chatMode;

    if (
      contextChanged &&
      previous.chatMode !== "standard" &&
      VOICE_ACTIVE_STATES.has(voiceSessionState)
    ) {
      setVoiceNotice(t("realtimeRestartAfterContextChange"));
    }

    voiceContextRef.current = next;
  }, [chatMode, conversationId, projectId, t, voiceSessionState]);

  const handleModeChange = useCallback(
    (mode: ChatMode) => {
      setSessionModeOverride(mode === projectDefaultMode ? null : mode);
      if (!conversationId) {
        return;
      }
      setConversationModeOverrides((prev) => {
        if (mode === projectDefaultMode) {
          if (!(conversationId in prev)) {
            return prev;
          }
          const next = { ...prev };
          delete next[conversationId];
          return next;
        }
        return {
          ...prev,
          [conversationId]: mode,
        };
      });
    },
    [conversationId, projectDefaultMode],
  );

  const handleStopGenerating = useCallback(() => {
    streamAbortReasonRef.current = "user";
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    setIsStreamingActive(false);
  }, []);

  const llmModelId = getPipelineModelId(pipelineItems, "llm", "qwen3.5-plus");
  const syntheticModeAvailable = modelSupportsCapability(
    catalogItems,
    llmModelId,
    "vision",
  );
  const syntheticVideoAvailable = modelSupportsCapability(
    catalogItems,
    llmModelId,
    "video",
  );
  const webSearchAvailable = modelSupportsCapability(
    catalogItems,
    llmModelId,
    "web_search",
  );
  const isStandardMode = chatMode === "standard";
  const isRealtimeMode =
    Boolean(conversationId) &&
    Boolean(projectId) &&
    !isConversationPending &&
    (chatMode === "omni_realtime" ||
      (chatMode === "synthetic_realtime" && syntheticModeAvailable));
  const noConversation = !conversationId;
  const interactionDisabled = noConversation || isConversationPending;
  const workspaceHint = noConversation
    ? t("emptyHint")
    : isRealtimeMode
      ? t("realtimeWorkspaceHint")
    : messages.length === 0 && !loadingMessages
      ? t("emptyConversationHint")
      : t("description");
  const currentModeLabel =
    chatMode === "omni_realtime"
      ? t("mode.omni")
      : chatMode === "synthetic_realtime"
        ? t("mode.synthetic")
        : t("mode.standard");
  const inspectorVariant = viewportWidth >= 1024 ? "overlay" : "sheet";

  return (
    <div className="chat-interface">
      <header
        className="chat-workspace-header"
        data-testid="chat-workspace-header"
      >
        <div className="chat-workspace-copy">
          <div className="chat-workspace-kicker">{t("title")}</div>
          <div className="chat-workspace-description">{workspaceHint}</div>
        </div>

        <div className="chat-workspace-controls">
          <ChatModePanel
            chatMode={chatMode}
            projectDefaultMode={projectDefaultMode}
            syntheticModeAvailable={syntheticModeAvailable}
            onModeChange={handleModeChange}
            disabled={interactionDisabled}
          />
          {conversationId ? (
            <span
              className="chat-workspace-badge"
              data-testid="chat-toolbar-state"
            >
              {currentModeLabel} ·{" "}
              {t("toolbar.messages", { count: messages.length })}
            </span>
          ) : null}
        </div>
      </header>

      <div
        className={`chat-interface-body chat-interface-body--${inspectorVariant}${inspectorState.open ? " has-inspector" : ""}`}
      >
        {loadingMessages && (
          <div className="chat-messages">
            <div className="chat-empty">...</div>
          </div>
        )}

        {!loadingMessages && (
          <ChatMessageList
            ref={messageListRef}
            messages={messages}
            onMessagesChange={setMessages}
            isTyping={isTyping}
            isCompactViewport={viewportWidth < 768}
            conversationId={conversationId}
            noConversation={noConversation}
            messageInspectorOverrides={messageInspectorOverrides}
            onOpenInspector={openInspector}
            onError={setVoiceNotice}
          />
        )}

        {!loadingMessages ? (
          <ConversationInspector
            variant={inspectorVariant}
            inspectorState={inspectorState}
            messages={messages}
            overrides={messageInspectorOverrides}
            uiMode={uiMode}
            memoryDetails={memoryDetails}
            memoryWriteDetails={memoryWriteDetails}
            memoryStatuses={memoryStatuses}
            memoryWriteStatuses={memoryWriteStatuses}
            onClose={() =>
              setInspectorState((current) => ({
                ...current,
                open: false,
              }))
            }
            onTabChange={(tab, section) =>
              setInspectorState((current) => ({
                ...current,
                tab,
                section: section ?? null,
              }))
            }
            onUiModeChange={setUiMode}
            onEnsureMemoryDetail={ensureMemoryDetail}
            onEnsureMemoryWriteDetail={ensureMemoryWriteDetail}
            onUpdateMemory={handleUpdateMemory}
            onDeleteMemory={handleDeleteMemory}
            onPromoteMemory={handlePromoteMemory}
          />
        ) : null}
      </div>

      {isStreamingActive && (
        <div className="chat-stop-generating">
          <button
            type="button"
            className="chat-stop-btn"
            onClick={handleStopGenerating}
          >
            <svg width={14} height={14} viewBox="0 0 24 24" fill="currentColor">
              <rect x={6} y={6} width={12} height={12} rx={2} />
            </svg>
            {t("stopGenerating")}
          </button>
        </div>
      )}

      <div
        className={`chat-composer-shell${isRealtimeMode ? " has-realtime-panel" : ""}`}
      >
        {voiceNotice ? (
          <div className="chat-voice-indicator is-error">{voiceNotice}</div>
        ) : null}
        {isRealtimeMode && conversationId && projectId ? (
          <RealtimeVoicePanel
            chatMode={chatMode}
            conversationId={conversationId}
            projectId={projectId}
            allowVideoInput={syntheticVideoAvailable}
            onTurnComplete={handleRealtimeTurnComplete}
            onTurnPersisted={handleRealtimeTurnPersisted}
            onTranscriptUpdate={handleLiveTranscriptUpdate}
            onError={handleRealtimeVoiceError}
            onStateChange={setVoiceSessionState}
          />
        ) : (
          <div className="chat-input-bar-voice">
            {isStandardMode && conversationId && projectId ? (
              <StandardVoiceControls
                conversationId={conversationId}
                projectId={projectId}
                isTyping={isTyping}
                disabled={interactionDisabled}
                onDictationDraftChange={handleLiveDictationDraftChange}
                onDictationStateChange={setIsLiveDictating}
                onError={setVoiceNotice}
              />
            ) : null}
            <ChatInputBar
              onSend={(content, options) => void handleSend(content, options)}
              disabled={interactionDisabled}
              isTyping={isTyping || isStreamingActive}
              isStandardMode={isStandardMode}
              searchAvailable={webSearchAvailable}
              autoReadEnabled={autoReadEnabled}
              onAutoReadToggle={() => setAutoReadEnabled((state) => !state)}
              liveExternalInputText={liveDictationText}
              isLiveExternalInputActive={isLiveDictating}
            />
          </div>
        )}
      </div>
    </div>
  );
}
