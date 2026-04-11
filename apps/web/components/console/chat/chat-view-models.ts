import {
  type ChatMetaRailItem,
  type Message,
  type MessageMemoryWriteDetail,
  type MessageInspectorOverride,
  type MemoryWriteSummaryItem,
  type MemoryWriteSummaryView,
  type RetrievalSummaryView,
  type ThinkingSummaryView,
} from "../chat-types";

export type InspectorTranslationFn = (
  key: string,
  values?: Record<string, string | number>,
) => string;

function getOverrideKey(messageId: string, targetMemoryId: string): string {
  return `${messageId}:${targetMemoryId}`;
}

function resolveMemoryOverride(
  messageId: string,
  targetMemoryId: string | null | undefined,
  overrides: Record<string, MessageInspectorOverride>,
): MessageInspectorOverride | null {
  if (!targetMemoryId) {
    return null;
  }
  return overrides[getOverrideKey(messageId, targetMemoryId)] ?? null;
}

export function buildSourceSummary(
  message: Message,
  t: InspectorTranslationFn,
): ChatMetaRailItem | null {
  const count = message.sources?.length ?? 0;
  if (!count) {
    return null;
  }
  return {
    key: "sources",
    label: t("inspector.meta.sources", { count }),
    tab: "context",
    section: "sources",
    count,
  };
}

export function buildRetrievalSummary(
  message: Message,
  t: InspectorTranslationFn,
): RetrievalSummaryView {
  const trace = message.retrievalTrace;
  const contextLevel = trace?.context_level ?? null;
  const selectedMemories =
    (trace?.selected_memories?.length ?? 0) > 0
      ? trace?.selected_memories ?? []
      : trace?.memories ?? [];
  const memoryCount =
    selectedMemories.length;
  const materialCount =
    (trace?.knowledge_chunks.length ?? 0) +
    (trace?.linked_file_chunks.length ?? 0) +
    (trace?.evidence_hits?.length ?? 0) +
    (trace?.view_hits?.length ?? 0);

  if (!trace || contextLevel === "none") {
    return {
      contextLevel,
      memoryCount,
      materialCount,
      label: null,
    };
  }

  if (contextLevel === "profile_only") {
    return {
      contextLevel,
      memoryCount,
      materialCount,
      label: t("inspector.meta.profile"),
    };
  }

  if (contextLevel === "memory_only") {
    return {
      contextLevel,
      memoryCount,
      materialCount,
      label: t("inspector.meta.memoryOnly", {
        memoryCount,
      }),
    };
  }

  return {
    contextLevel,
    memoryCount,
    materialCount,
    label: t("inspector.meta.fullRag", {
      memoryCount,
      materialCount,
    }),
  };
}

function resolveMemoryBadgeKey(item: {
  triageAction: string | null;
  status: string | null;
  memoryType: "permanent" | "temporary" | null;
}): MemoryWriteSummaryItem["badgeKey"] {
  if (item.triageAction === "discard") {
    return "not_written";
  }

  if (
    item.triageAction === "append" ||
    item.triageAction === "merge" ||
    item.triageAction === "replace" ||
    item.triageAction === "supersede" ||
    item.triageAction === "conflict" ||
    item.status === "merged" ||
    item.status === "appended" ||
    item.status === "replaced"
  ) {
    return "merged";
  }

  if (item.triageAction === "promote") {
    return "long_term";
  }

  if (item.memoryType === "temporary" || item.status === "temporary") {
    return "temporary";
  }

  if (item.memoryType === "permanent" || item.status === "permanent") {
    return "long_term";
  }

  return "not_written";
}

export function buildMemoryWriteSummary(
  message: Message,
  overrides: Record<string, MessageInspectorOverride>,
  t: InspectorTranslationFn,
  memoryWriteDetail?: MessageMemoryWriteDetail | null,
): MemoryWriteSummaryView {
  if (memoryWriteDetail?.items?.length) {
    const items = memoryWriteDetail.items.map((item, index) => {
      const targetMemoryId = item.target_memory_id ?? null;
      const override = resolveMemoryOverride(message.id, targetMemoryId, overrides);
      const hidden = override?.hidden === true;
      const triageAction = item.decision ?? null;
      const status = override?.status ?? memoryWriteDetail.run?.status ?? null;
      const memoryType =
        override?.memoryType ??
        (triageAction === "promote"
          ? "permanent"
          : item.proposed_memory_kind === "episodic"
            ? "temporary"
            : null);
      const metadata = item.metadata_json ?? {};
      const evidenceCount = Array.isArray(metadata.evidence_ids)
        ? metadata.evidence_ids.length
        : 0;

      return {
        id: item.id || `${message.id}-write-${index}`,
        fact: override?.fact ?? item.candidate_text,
        category: item.category,
        importance: item.importance,
        triageAction,
        triageReason: item.reason ?? null,
        status,
        targetMemoryId,
        memoryType,
        badgeKey: resolveMemoryBadgeKey({
          triageAction,
          status,
          memoryType,
        }),
        isActionable:
          triageAction !== "discard" &&
          Boolean(targetMemoryId) &&
          !hidden,
        evidenceCount,
        hidden,
      };
    });

    const visibleItems = items.filter((item) => !item.hidden).map((item) => ({
      id: item.id,
      fact: item.fact,
      category: item.category,
      importance: item.importance,
      triageAction: item.triageAction,
      triageReason: item.triageReason,
      status: item.status,
      targetMemoryId: item.targetMemoryId,
      memoryType: item.memoryType,
      badgeKey: item.badgeKey,
      isActionable: item.isActionable,
      evidenceCount: item.evidenceCount,
    }));
    const count = visibleItems.filter((item) => item.triageAction !== "discard").length;
    return {
      count,
      label: count > 0 ? t("inspector.meta.memoryWrite", { count }) : null,
      items: visibleItems,
    };
  }

  if (message.memory_write_preview?.items?.length) {
    const preview = message.memory_write_preview;
    const items = preview.items.map((item, index) => {
      const override = resolveMemoryOverride(
        message.id,
        item.target_memory_id,
        overrides,
      );
      const hidden = override?.hidden === true;
      const triageAction = item.triage_action ?? null;
      const status = override?.status ?? item.status ?? null;
      const memoryType = override?.memoryType ?? item.memory_type ?? null;

      return {
        id: item.id || `${message.id}-preview-${index}`,
        fact: override?.fact ?? item.fact,
        category: item.category,
        importance: item.importance,
        triageAction,
        triageReason: item.triage_reason ?? null,
        status,
        targetMemoryId: item.target_memory_id ?? null,
        memoryType,
        badgeKey: resolveMemoryBadgeKey({
          triageAction,
          status,
          memoryType,
        }),
        isActionable:
          triageAction !== "discard" &&
          Boolean(item.target_memory_id) &&
          !hidden,
        evidenceCount: item.evidence_count ?? 0,
        hidden,
      };
    });

    const visibleItems = items.filter((item) => !item.hidden).map((item) => ({
      id: item.id,
      fact: item.fact,
      category: item.category,
      importance: item.importance,
      triageAction: item.triageAction,
      triageReason: item.triageReason,
      status: item.status,
      targetMemoryId: item.targetMemoryId,
      memoryType: item.memoryType,
      badgeKey: item.badgeKey,
      isActionable: item.isActionable,
      evidenceCount: item.evidenceCount,
    }));
    const count =
      typeof preview.written_count === "number"
        ? preview.written_count
        : visibleItems.filter((item) => item.triageAction !== "discard").length;
    return {
      count,
      label:
        message.memories_extracted ??
        preview.summary ??
        (count > 0 ? t("inspector.meta.memoryWrite", { count }) : null),
      items: visibleItems,
    };
  }

  const baseItems = (message.extracted_facts ?? []).map((fact, index) => {
    const override = resolveMemoryOverride(
      message.id,
      fact.target_memory_id,
      overrides,
    );
    const hidden = override?.hidden === true;
    const triageAction = fact.triage_action ?? null;
    const status = override?.status ?? fact.status ?? null;
    const memoryType = override?.memoryType ?? null;

    return {
      id: fact.target_memory_id || `${message.id}-fact-${index}`,
      fact: override?.fact ?? fact.fact,
      category: fact.category,
      importance: fact.importance,
      triageAction,
      triageReason: fact.triage_reason ?? null,
      status,
      targetMemoryId: fact.target_memory_id ?? null,
      memoryType,
      badgeKey: resolveMemoryBadgeKey({
        triageAction,
        status,
        memoryType,
      }),
      isActionable:
        triageAction !== "discard" && Boolean(fact.target_memory_id) && !hidden,
      evidenceCount: 0,
      hidden,
    };
  });

  const items = baseItems.filter((item) => !item.hidden).map((item) => ({
    id: item.id,
    fact: item.fact,
    category: item.category,
    importance: item.importance,
    triageAction: item.triageAction,
    triageReason: item.triageReason,
    status: item.status,
    targetMemoryId: item.targetMemoryId,
    memoryType: item.memoryType,
    badgeKey: item.badgeKey,
    isActionable: item.isActionable,
    evidenceCount: item.evidenceCount,
  }));
  const count = items.filter((item) => item.triageAction !== "discard").length;

  return {
    count,
    label: count > 0 ? t("inspector.meta.memoryWrite", { count }) : null,
    items,
  };
}

export function buildThinkingSummary(
  message: Message,
  t: InspectorTranslationFn,
): ThinkingSummaryView {
  const content = message.reasoningContent?.trim() || null;
  return {
    content,
    label: content ? t("inspector.meta.thinking") : null,
  };
}

export function buildChatMetaRailItems(
  message: Message,
  overrides: Record<string, MessageInspectorOverride>,
  t: InspectorTranslationFn,
): ChatMetaRailItem[] {
  const sourceItem = buildSourceSummary(message, t);
  const retrievalSummary = buildRetrievalSummary(message, t);
  const memorySummary = buildMemoryWriteSummary(message, overrides, t);
  const thinkingSummary = buildThinkingSummary(message, t);

  return [
    sourceItem,
    retrievalSummary.label
      ? {
          key: "context",
          label: retrievalSummary.label,
          tab: "context",
          section:
            retrievalSummary.contextLevel === "profile_only" ? "profile" : "recent",
        }
      : null,
    memorySummary.label
      ? {
          key: "memory_write",
          label: memorySummary.label,
          tab: "memory_write",
          count: memorySummary.count,
        }
      : null,
    thinkingSummary.label
      ? {
          key: "thinking",
          label: thinkingSummary.label,
          tab: "thinking",
        }
      : null,
  ].filter((item): item is ChatMetaRailItem => item !== null);
}

export function getMessageInspectorOverrideKey(
  messageId: string,
  targetMemoryId: string,
): string {
  return getOverrideKey(messageId, targetMemoryId);
}
