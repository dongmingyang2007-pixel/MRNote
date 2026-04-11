"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { ConsoleEmptyState, ConsoleInspectorPanel } from "../ConsolePrimitives";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ConversationInspectorTabs } from "./ConversationInspectorTabs";
import {
  buildMemoryWriteSummary,
  buildRetrievalSummary,
  buildThinkingSummary,
} from "./chat-view-models";
import type {
  InspectorSection,
  InspectorState,
  InspectorTab,
  Message,
  MessageMemoryWriteDetail,
  MessageInspectorOverride,
  MemoryWriteSummaryView,
  RetrievalTraceChunk,
  RetrievalTraceMemory,
} from "../chat-types";

type InspectorVariant = "docked" | "overlay" | "sheet";

export interface InspectorMemoryRecord {
  id: string;
  content: string;
  category: string;
  type: "permanent" | "temporary";
  metadata_json?: Record<string, unknown>;
  confidence?: number | null;
  observed_at?: string | null;
  valid_from?: string | null;
  valid_to?: string | null;
  last_confirmed_at?: string | null;
  evidences?: Array<{
    id: string;
    quote_text: string;
    source_type?: string | null;
    confidence?: number | null;
    created_at?: string | null;
  }>;
  views?: Array<{
    id: string;
    view_type?: string | null;
    content: string;
  }>;
  timeline_events?: Array<{
    id: string;
    content: string;
    observed_at?: string | null;
    node_status?: string | null;
  }>;
  write_history?: Array<{
    id: string;
    decision?: string | null;
    reason?: string | null;
    created_at?: string | null;
  }>;
  created_at?: string;
  updated_at?: string;
}

interface ConversationInspectorProps {
  inspectorState: InspectorState;
  variant: InspectorVariant;
  messages: Message[];
  overrides: Record<string, MessageInspectorOverride>;
  uiMode: "user" | "debug";
  memoryDetails: Record<string, InspectorMemoryRecord>;
  memoryWriteDetails: Record<string, MessageMemoryWriteDetail | null>;
  memoryStatuses: Record<
    string,
    "idle" | "loading" | "saving" | "deleting" | "promoting"
  >;
  memoryWriteStatuses: Record<string, "idle" | "loading">;
  onClose: () => void;
  onTabChange: (tab: InspectorTab, section?: InspectorSection) => void;
  onUiModeChange: (mode: "user" | "debug") => void;
  onEnsureMemoryDetail: (memoryId: string) => Promise<void> | void;
  onEnsureMemoryWriteDetail: (messageId: string) => Promise<void> | void;
  onUpdateMemory: (payload: {
    messageId: string;
    memoryId: string;
    content: string;
  }) => Promise<void>;
  onDeleteMemory: (payload: {
    messageId: string;
    memoryId: string;
  }) => Promise<void>;
  onPromoteMemory: (payload: {
    messageId: string;
    memoryId: string;
  }) => Promise<void>;
}

function formatRetrievalPercent(value?: number | null): string | null {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return null;
  }
  return `${Math.round(value * 100)}%`;
}

function formatRetrievalSourceLabel(
  source: string | null | undefined,
  t: (key: string) => string,
): string {
  const labels: Record<string, string> = {
    static: t("retrievalSourceStatic"),
    semantic: t("retrievalSourceSemantic"),
    lexical: t("retrievalSourceLexical"),
    graph_parent: t("retrievalSourceGraphParent"),
    graph_child: t("retrievalSourceGraphChild"),
    graph_edge: t("retrievalSourceGraphEdge"),
    recent_temporary: t("retrievalSourceRecentTemporary"),
    context: t("retrievalSourceContext"),
  };
  if (!source) {
    return labels.context;
  }
  return labels[source] || source.replace(/_/g, " ");
}

function formatRetrievalMemoryKind(
  memoryKind: string | null | undefined,
  t: (key: string) => string,
): string {
  const labels: Record<string, string> = {
    profile: t("retrievalKindProfile"),
    preference: t("retrievalKindPreference"),
    goal: t("retrievalKindGoal"),
    episodic: t("retrievalKindEpisodic"),
    fact: t("retrievalKindFact"),
    summary: t("retrievalKindSummary"),
  };
  if (!memoryKind) {
    return t("retrievalKindUnknown");
  }
  return labels[memoryKind] || memoryKind;
}

function badgeLabel(
  badgeKey: "long_term" | "temporary" | "merged" | "not_written",
  t: (key: string) => string,
): string {
  const labels: Record<typeof badgeKey, string> = {
    long_term: t("inspector.memory.badge.longTerm"),
    temporary: t("inspector.memory.badge.temporary"),
    merged: t("inspector.memory.badge.merged"),
    not_written: t("inspector.memory.badge.notWritten"),
  };
  return labels[badgeKey];
}

function summarizeChunkLabel(
  chunk: RetrievalTraceChunk,
  fallback: string,
): string {
  return chunk.filename?.trim() || fallback;
}

function summarizeMemoryGroups(memories: RetrievalTraceMemory[]) {
  const recent: RetrievalTraceMemory[] = [];
  const profile: RetrievalTraceMemory[] = [];

  for (const memory of memories) {
    if (memory.type === "temporary" || memory.source === "recent_temporary") {
      recent.push(memory);
      continue;
    }
    profile.push(memory);
  }

  return { recent, profile };
}

function EmptyBody({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <ConsoleEmptyState
      className="chat-inspector-empty"
      title={title}
      description={description}
    />
  );
}

function formatOutcomeWeight(value?: number | null): string | null {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return null;
  }
  return `${parseFloat(value.toFixed(2))}x`;
}

function summarizeTraceIds(values?: string[] | null, limit = 3): string | null {
  const cleaned = Array.from(
    new Set(
      (values || []).filter(
        (value): value is string => typeof value === "string" && value.trim().length > 0,
      ),
    ),
  );
  if (!cleaned.length) {
    return null;
  }
  const visible = cleaned.slice(0, limit).join(" · ");
  return cleaned.length > limit
    ? `${visible} +${cleaned.length - limit}`
    : visible;
}

function TraceDiagnostics({
  t,
  selectionReason,
  suppressionReason,
  outcomeWeight,
  episodeIds,
  usedPlaybookIds,
  conflictedMemoryIds,
}: {
  t: (key: string) => string;
  selectionReason?: string | null;
  suppressionReason?: string | null;
  outcomeWeight?: number | null;
  episodeIds?: string[] | null;
  usedPlaybookIds?: string[] | null;
  conflictedMemoryIds?: string[] | null;
}) {
  const selectionLabel = selectionReason?.trim() || null;
  const suppressionLabel = suppressionReason?.trim() || null;
  const outcomeLabel = formatOutcomeWeight(outcomeWeight);
  const episodesLabel = summarizeTraceIds(episodeIds);
  const playbooksLabel = summarizeTraceIds(usedPlaybookIds);
  const conflictsLabel = summarizeTraceIds(conflictedMemoryIds);

  return (
    <>
      {selectionLabel ? (
        <div className="chat-memory-write-subcopy">
          {t("inspector.context.selectionReason")}: {selectionLabel}
        </div>
      ) : null}
      {suppressionLabel ? (
        <div className="chat-memory-write-subcopy">
          {t("inspector.context.suppressionReason")}: {suppressionLabel}
        </div>
      ) : null}
      {outcomeLabel ? (
        <div className="chat-memory-write-subcopy">
          {t("inspector.context.outcomeWeight")}: {outcomeLabel}
        </div>
      ) : null}
      {episodesLabel ? (
        <div className="chat-memory-write-subcopy">
          {t("inspector.context.episodes")}: {episodesLabel}
        </div>
      ) : null}
      {playbooksLabel ? (
        <div className="chat-memory-write-subcopy">
          {t("inspector.context.playbooks")}: {playbooksLabel}
        </div>
      ) : null}
      {conflictsLabel ? (
        <div className="chat-memory-write-subcopy">
          {t("inspector.context.conflicts")}: {conflictsLabel}
        </div>
      ) : null}
    </>
  );
}

function MemoryWriteTabContent({
  message,
  memorySummary,
  memoryWriteDetail,
  memoryWriteStatus,
  memoryDetails,
  memoryStatuses,
  onEnsureMemoryDetail,
  onUpdateMemory,
  onDeleteMemory,
  onPromoteMemory,
}: {
  message: Message;
  memorySummary: MemoryWriteSummaryView;
  memoryWriteDetail: MessageMemoryWriteDetail | null;
  memoryWriteStatus: "idle" | "loading";
  memoryDetails: Record<string, InspectorMemoryRecord>;
  memoryStatuses: Record<
    string,
    "idle" | "loading" | "saving" | "deleting" | "promoting"
  >;
  onEnsureMemoryDetail: (memoryId: string) => Promise<void> | void;
  onUpdateMemory: (payload: {
    messageId: string;
    memoryId: string;
    content: string;
  }) => Promise<void>;
  onDeleteMemory: (payload: {
    messageId: string;
    memoryId: string;
  }) => Promise<void>;
  onPromoteMemory: (payload: {
    messageId: string;
    memoryId: string;
  }) => Promise<void>;
}) {
  const t = useTranslations("console-chat");
  const [expandedMemoryIds, setExpandedMemoryIds] = useState<
    Record<string, boolean>
  >({});
  const [editingMemoryId, setEditingMemoryId] = useState<string | null>(null);
  const [editingDraft, setEditingDraft] = useState("");

  const handleExpandMemory = async (memoryId: string | null) => {
    if (!memoryId) {
      return;
    }
    setExpandedMemoryIds((prev) => ({
      ...prev,
      [memoryId]: !prev[memoryId],
    }));
    if (!expandedMemoryIds[memoryId] && !memoryDetails[memoryId]) {
      await onEnsureMemoryDetail(memoryId);
    }
  };

  if (!memorySummary.items.length) {
    return (
      <EmptyBody
        title={t("inspector.memory.emptyTitle")}
        description={t("inspector.memory.emptyDescription")}
      />
    );
  }

  return (
    <div className="chat-memory-write-list">
      {memoryWriteDetail?.run ? (
        <article className="chat-memory-write-item">
          <div className="chat-memory-write-copy">
            <div className="chat-memory-write-text">
              {memoryWriteDetail.run.status || "pending"}
            </div>
            <div className="chat-memory-write-meta">
              {memoryWriteDetail.run.extraction_model ? (
                <span className="chat-inspector-pill">
                  {memoryWriteDetail.run.extraction_model}
                </span>
              ) : null}
              {memoryWriteDetail.run.consolidation_model ? (
                <span className="chat-inspector-pill">
                  {memoryWriteDetail.run.consolidation_model}
                </span>
              ) : null}
            </div>
          </div>
          {memoryWriteDetail.run.error ? (
            <div className="chat-memory-write-subcopy">
              {memoryWriteDetail.run.error}
            </div>
          ) : null}
        </article>
      ) : memoryWriteStatus === "loading" ? (
        <div className="chat-memory-write-loading">
          {t("inspector.memory.loading")}
        </div>
      ) : null}
      {memorySummary.items.map((item) => {
        const detail = item.targetMemoryId
          ? memoryDetails[item.targetMemoryId]
          : null;
        const status =
          (item.targetMemoryId && memoryStatuses[item.targetMemoryId]) || "idle";
        const isExpanded = item.targetMemoryId
          ? Boolean(expandedMemoryIds[item.targetMemoryId])
          : false;
        const isEditing =
          item.targetMemoryId !== null && editingMemoryId === item.targetMemoryId;
        const canPromote =
          item.targetMemoryId !== null &&
          (detail?.type || item.memoryType || item.status) === "temporary";

        return (
          <article key={item.id} className="chat-memory-write-item">
            <button
              type="button"
              className="chat-memory-write-head"
              onClick={() => void handleExpandMemory(item.targetMemoryId)}
              disabled={!item.targetMemoryId}
            >
              <div className="chat-memory-write-copy">
                <div className="chat-memory-write-text">{item.fact}</div>
                <div className="chat-memory-write-meta">
                  <span className="chat-inspector-pill is-primary">
                    {badgeLabel(item.badgeKey, t)}
                  </span>
                  {item.category ? (
                    <span className="chat-inspector-pill">{item.category}</span>
                  ) : null}
                  {typeof item.evidenceCount === "number" && item.evidenceCount > 0 ? (
                    <span className="chat-inspector-pill">
                      {item.evidenceCount}
                    </span>
                  ) : null}
                </div>
              </div>
              {item.targetMemoryId ? (
                <span className="chat-memory-write-expand">
                  {isExpanded
                    ? t("inspector.memory.collapse")
                    : t("inspector.memory.expand")}
                </span>
              ) : null}
            </button>

            <div className="chat-memory-write-subcopy">
              {item.triageReason || t("inspector.memory.noReason")}
            </div>

            {isExpanded ? (
              <div className="chat-memory-write-panel">
                {status === "loading" ? (
                  <div className="chat-memory-write-loading">
                    {t("inspector.memory.loading")}
                  </div>
                ) : null}

                {isEditing ? (
                  <div className="chat-memory-write-editor">
                    <textarea
                      className="chat-memory-write-textarea"
                      value={editingDraft}
                      onChange={(event) => setEditingDraft(event.target.value)}
                      rows={4}
                    />
                    <div className="chat-memory-write-actions">
                      <button
                        type="button"
                        className="chat-inspector-button is-primary"
                        disabled={status !== "idle" || !editingDraft.trim()}
                        onClick={async () => {
                          if (!item.targetMemoryId) {
                            return;
                          }
                          await onUpdateMemory({
                            messageId: message.id,
                            memoryId: item.targetMemoryId,
                            content: editingDraft.trim(),
                          });
                          setEditingMemoryId(null);
                        }}
                      >
                        {t("inspector.memory.save")}
                      </button>
                      <button
                        type="button"
                        className="chat-inspector-button"
                        onClick={() => setEditingMemoryId(null)}
                      >
                        {t("inspector.memory.cancel")}
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    {detail ? (
                      <div className="chat-memory-write-detail">
                        <div>{detail.content}</div>
                        <div className="chat-memory-write-detail-meta">
                          <span>{detail.id}</span>
                          <span>{detail.type}</span>
                        </div>
                        {detail.evidences?.length ? (
                          <div className="chat-memory-write-subcopy">
                            {detail.evidences[0]?.quote_text}
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                    {item.isActionable ? (
                      <div className="chat-memory-write-actions">
                        <button
                          type="button"
                          className="chat-inspector-button"
                          disabled={status !== "idle"}
                          onClick={async () => {
                            if (!item.targetMemoryId) {
                              return;
                            }
                            if (!detail) {
                              await onEnsureMemoryDetail(item.targetMemoryId);
                            }
                            setEditingMemoryId(item.targetMemoryId);
                            setEditingDraft(detail?.content || item.fact);
                          }}
                        >
                          {t("inspector.memory.edit")}
                        </button>
                        <button
                          type="button"
                          className="chat-inspector-button"
                          disabled={status !== "idle"}
                          onClick={async () => {
                            if (!item.targetMemoryId) {
                              return;
                            }
                            await onDeleteMemory({
                              messageId: message.id,
                              memoryId: item.targetMemoryId,
                            });
                          }}
                        >
                          {t("inspector.memory.delete")}
                        </button>
                        {canPromote ? (
                          <button
                            type="button"
                            className="chat-inspector-button"
                            disabled={status !== "idle"}
                            onClick={async () => {
                              if (!item.targetMemoryId) {
                                return;
                              }
                              await onPromoteMemory({
                                messageId: message.id,
                                memoryId: item.targetMemoryId,
                              });
                            }}
                          >
                            {t("inspector.memory.promote")}
                          </button>
                        ) : null}
                      </div>
                    ) : null}
                  </>
                )}
              </div>
            ) : null}
          </article>
        );
      })}
    </div>
  );
}

function InspectorInner({
  inspectorState,
  messages,
  overrides,
  uiMode,
  memoryDetails,
  memoryWriteDetails,
  memoryStatuses,
  memoryWriteStatuses,
  onClose,
  onTabChange,
  onUiModeChange,
  onEnsureMemoryDetail,
  onEnsureMemoryWriteDetail,
  onUpdateMemory,
  onDeleteMemory,
  onPromoteMemory,
}: Omit<ConversationInspectorProps, "variant">) {
  const t = useTranslations("console-chat");
  const sectionHostRef = useRef<HTMLDivElement | null>(null);

  const message = useMemo(
    () =>
      messages.find((entry) => entry.id === inspectorState.messageId) ?? null,
    [inspectorState.messageId, messages],
  );
  const retrievalSummary = useMemo(
    () => (message ? buildRetrievalSummary(message, t) : null),
    [message, t],
  );
  const memorySummary = useMemo(
    () =>
      message
        ? buildMemoryWriteSummary(
            message,
            overrides,
            t,
            memoryWriteDetails[message.id] ?? null,
          )
        : { count: 0, label: null, items: [] },
    [message, memoryWriteDetails, overrides, t],
  );
  const thinkingSummary = useMemo(
    () => (message ? buildThinkingSummary(message, t) : { content: null, label: null }),
    [message, t],
  );
  const trace = message?.retrievalTrace ?? null;
  const memoryGroups = useMemo(
    () =>
      summarizeMemoryGroups(
        (trace?.selected_memories?.length ?? 0) > 0
          ? trace?.selected_memories ?? []
          : trace?.memories ?? [],
      ),
    [trace?.memories, trace?.selected_memories],
  );

  useEffect(() => {
    if (
      inspectorState.open &&
      inspectorState.tab === "memory_write" &&
      message?.id
    ) {
      void onEnsureMemoryWriteDetail(message.id);
    }
  }, [inspectorState.open, inspectorState.tab, message?.id, onEnsureMemoryWriteDetail]);

  useEffect(() => {
    if (!inspectorState.open || !inspectorState.section) {
      return;
    }
    const host = sectionHostRef.current;
    if (!host) {
      return;
    }
    const target = host.querySelector<HTMLElement>(
      `[data-inspector-section="${inspectorState.section}"]`,
    );
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [inspectorState.open, inspectorState.section, inspectorState.tab]);

  const tabOptions = [
    { key: "context" as const, label: t("inspector.tabs.context") },
    { key: "memory_write" as const, label: t("inspector.tabs.memory") },
    ...(uiMode === "debug"
      ? [{ key: "debug" as const, label: t("inspector.tabs.debug") }]
      : []),
  ];

  const panelTitle =
    inspectorState.tab === "context"
      ? t("inspector.context.title")
      : inspectorState.tab === "memory_write"
        ? t("inspector.memory.title")
        : inspectorState.tab === "thinking"
          ? t("inspector.thinking.title")
          : t("inspector.debug.title");
  const panelDescription =
    inspectorState.tab === "context"
      ? t("inspector.context.description")
      : inspectorState.tab === "memory_write"
        ? t("inspector.memory.description")
        : inspectorState.tab === "thinking"
          ? t("inspector.thinking.description")
          : t("inspector.debug.description");

  const action = (
    <div className="chat-inspector-header-actions">
      <button
        type="button"
        className="chat-inspector-debug-toggle"
        onClick={() => onUiModeChange(uiMode === "debug" ? "user" : "debug")}
      >
        {uiMode === "debug"
          ? t("inspector.actions.userMode")
          : t("inspector.actions.debugMode")}
      </button>
      <button
        type="button"
        className="chat-inspector-close"
        onClick={onClose}
        aria-label={t("inspector.actions.close")}
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
          <path d="M18 6 6 18" />
          <path d="m6 6 12 12" />
        </svg>
      </button>
    </div>
  );

  const body = !message ? (
    <EmptyBody
      title={t("inspector.empty.title")}
      description={t("inspector.empty.description")}
    />
  ) : (
    <div className="chat-inspector-body" ref={sectionHostRef}>
      <ConversationInspectorTabs
        activeTab={inspectorState.tab}
        options={tabOptions}
        onTabChange={(tab) => onTabChange(tab)}
      />

      {inspectorState.tab === "context" ? (
        <div className="chat-inspector-content">
          {trace?.layer_hits ? (
            <section className="chat-inspector-section">
              <header className="chat-inspector-section-header">
                <h3>{t("inspector.context.layers")}</h3>
              </header>
              <div className="chat-inspector-card-list">
                <article className="chat-inspector-card">
                  <div className="chat-inspector-card-row">
                    {typeof trace.layer_hits.profile === "number" ? (
                      <span className="chat-inspector-pill">
                        {t("inspector.context.layerProfile")} {trace.layer_hits.profile}
                      </span>
                    ) : null}
                    {typeof trace.layer_hits.durable_facts === "number" ? (
                      <span className="chat-inspector-pill">
                        {t("inspector.context.layerFacts")} {trace.layer_hits.durable_facts}
                      </span>
                    ) : null}
                    {typeof trace.layer_hits.playbooks === "number" ? (
                      <span className="chat-inspector-pill">
                        {t("inspector.context.layerPlaybooks")} {trace.layer_hits.playbooks}
                      </span>
                    ) : null}
                    {typeof trace.layer_hits.episodic_timeline === "number" ? (
                      <span className="chat-inspector-pill">
                        {t("inspector.context.layerTimeline")} {trace.layer_hits.episodic_timeline}
                      </span>
                    ) : null}
                    {typeof trace.layer_hits.raw_evidence === "number" ? (
                      <span className="chat-inspector-pill">
                        {t("inspector.context.layerEvidence")} {trace.layer_hits.raw_evidence}
                      </span>
                    ) : null}
                  </div>
                  {trace.policy_flags?.length ? (
                    <div className="chat-memory-write-subcopy">
                      {trace.policy_flags.join(" · ")}
                    </div>
                  ) : null}
                  <TraceDiagnostics
                    t={t}
                    episodeIds={trace.episode_ids}
                    usedPlaybookIds={trace.used_playbook_ids}
                    conflictedMemoryIds={trace.conflicted_memory_ids}
                  />
                </article>
              </div>
            </section>
          ) : null}

          {message.sources?.length ? (
            <section
              className="chat-inspector-section"
              data-inspector-section="sources"
            >
              <header className="chat-inspector-section-header">
                <h3>{t("inspector.context.sources")}</h3>
              </header>
              <div className="chat-inspector-source-list">
                {message.sources.map((source, index) => (
                  <a
                    key={`${source.url}-${index}`}
                    className="chat-inspector-source-card"
                    href={source.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <span className="chat-inspector-source-title">
                      {source.title}
                    </span>
                    <span className="chat-inspector-source-meta">
                      {source.site_name || source.domain}
                    </span>
                    {source.summary?.trim() ? (
                      <span className="chat-inspector-source-summary">
                        {source.summary}
                      </span>
                    ) : null}
                  </a>
                ))}
              </div>
            </section>
          ) : null}

          {memoryGroups.profile.length ? (
            <section
              className="chat-inspector-section"
              data-inspector-section="profile"
            >
              <header className="chat-inspector-section-header">
                <h3>{t("inspector.context.profile")}</h3>
              </header>
              <div className="chat-inspector-card-list">
                {memoryGroups.profile.map((memory) => (
                  <article key={memory.id} className="chat-inspector-card">
                    <div className="chat-inspector-card-row">
                      <span className="chat-inspector-pill is-primary">
                        {formatRetrievalMemoryKind(memory.memory_kind, t)}
                      </span>
                      {memory.source ? (
                        <span className="chat-inspector-pill">
                          {formatRetrievalSourceLabel(memory.source, t)}
                        </span>
                      ) : null}
                      {formatRetrievalPercent(memory.score) ? (
                        <span className="chat-inspector-metric">
                          {formatRetrievalPercent(memory.score)}
                        </span>
                      ) : null}
                    </div>
                    {memory.category ? (
                      <div className="chat-inspector-card-title">
                        {memory.category}
                      </div>
                    ) : null}
                    <div className="chat-inspector-card-body">
                      {memory.content}
                    </div>
                    <TraceDiagnostics
                      t={t}
                      selectionReason={memory.selection_reason ?? memory.why_selected}
                      suppressionReason={memory.suppression_reason}
                      outcomeWeight={memory.outcome_weight}
                      episodeIds={memory.episode_ids}
                    />
                    {memory.supporting_quote ? (
                      <div className="chat-memory-write-subcopy">
                        {memory.supporting_quote}
                      </div>
                    ) : null}
                    {memory.supporting_file_excerpt ? (
                      <div className="chat-memory-write-subcopy">
                        {memory.supporting_file_excerpt}
                      </div>
                    ) : null}
                  </article>
                ))}
              </div>
            </section>
          ) : null}

          {memoryGroups.recent.length ? (
            <section
              className="chat-inspector-section"
              data-inspector-section="recent"
            >
              <header className="chat-inspector-section-header">
                <h3>{t("inspector.context.recent")}</h3>
              </header>
              <div className="chat-inspector-card-list">
                {memoryGroups.recent.map((memory) => (
                  <article key={memory.id} className="chat-inspector-card">
                    <div className="chat-inspector-card-row">
                      <span className="chat-inspector-pill">
                        {t("retrievalSourceRecentTemporary")}
                      </span>
                      {formatRetrievalPercent(memory.score) ? (
                        <span className="chat-inspector-metric">
                          {formatRetrievalPercent(memory.score)}
                        </span>
                      ) : null}
                    </div>
                    <div className="chat-inspector-card-body">
                      {memory.content}
                    </div>
                    <TraceDiagnostics
                      t={t}
                      selectionReason={memory.selection_reason ?? memory.why_selected}
                      suppressionReason={memory.suppression_reason}
                      outcomeWeight={memory.outcome_weight}
                      episodeIds={memory.episode_ids}
                    />
                    {memory.supporting_quote ? (
                      <div className="chat-memory-write-subcopy">
                        {memory.supporting_quote}
                      </div>
                    ) : null}
                    {memory.supporting_file_excerpt ? (
                      <div className="chat-memory-write-subcopy">
                        {memory.supporting_file_excerpt}
                      </div>
                    ) : null}
                  </article>
                ))}
              </div>
            </section>
          ) : null}

          {trace?.knowledge_chunks.length ? (
            <section
              className="chat-inspector-section"
              data-inspector-section="knowledge"
            >
              <header className="chat-inspector-section-header">
                <h3>{t("inspector.context.knowledge")}</h3>
              </header>
              <div className="chat-inspector-card-list">
                {trace.knowledge_chunks.map((chunk, index) => (
                  <article
                    key={`${chunk.id || chunk.data_item_id || "knowledge"}-${index}`}
                    className="chat-inspector-card"
                  >
                    <div className="chat-inspector-card-row">
                      <span className="chat-inspector-pill">
                        {summarizeChunkLabel(chunk, t("retrievalKnowledgeChunk"))}
                      </span>
                      {formatRetrievalPercent(chunk.score) ? (
                        <span className="chat-inspector-metric">
                          {formatRetrievalPercent(chunk.score)}
                        </span>
                      ) : null}
                    </div>
                    <div className="chat-inspector-card-body">
                      {chunk.chunk_text}
                    </div>
                    {chunk.why_selected ? (
                      <div className="chat-memory-write-subcopy">
                        {chunk.why_selected}
                      </div>
                    ) : null}
                  </article>
                ))}
              </div>
            </section>
          ) : null}

          {trace?.linked_file_chunks.length ? (
            <section
              className="chat-inspector-section"
              data-inspector-section="files"
            >
              <header className="chat-inspector-section-header">
                <h3>{t("inspector.context.files")}</h3>
              </header>
              <div className="chat-inspector-card-list">
                {trace.linked_file_chunks.map((chunk, index) => (
                  <article
                    key={`${chunk.id || chunk.data_item_id || "linked"}-${index}`}
                    className="chat-inspector-card"
                  >
                    <div className="chat-inspector-card-row">
                      <span className="chat-inspector-pill">
                        {summarizeChunkLabel(chunk, t("retrievalLinkedChunk"))}
                      </span>
                      {formatRetrievalPercent(chunk.score) ? (
                        <span className="chat-inspector-metric">
                          {formatRetrievalPercent(chunk.score)}
                        </span>
                      ) : null}
                    </div>
                    <div className="chat-inspector-card-body">
                      {chunk.chunk_text}
                    </div>
                    {chunk.why_selected ? (
                      <div className="chat-memory-write-subcopy">
                        {chunk.why_selected}
                      </div>
                    ) : null}
                    {chunk.memory_ids?.length ? (
                      <div className="chat-memory-write-subcopy">
                        {chunk.memory_ids.join(" · ")}
                      </div>
                    ) : null}
                  </article>
                ))}
              </div>
            </section>
          ) : null}

          {trace?.view_hits?.length ? (
            <section className="chat-inspector-section">
              <header className="chat-inspector-section-header">
                <h3>{t("inspector.context.views")}</h3>
              </header>
              <div className="chat-inspector-card-list">
                {trace.view_hits.map((view) => (
                  <article key={view.id} className="chat-inspector-card">
                    <div className="chat-inspector-card-row">
                      {view.view_type ? (
                        <span className="chat-inspector-pill is-primary">
                          {view.view_type}
                        </span>
                      ) : null}
                      {formatRetrievalPercent(view.score) ? (
                        <span className="chat-inspector-metric">
                          {formatRetrievalPercent(view.score)}
                        </span>
                      ) : null}
                    </div>
                    <div className="chat-inspector-card-body">
                      {view.snippet || view.content}
                    </div>
                    <TraceDiagnostics
                      t={t}
                      selectionReason={view.selection_reason ?? view.why_selected}
                      suppressionReason={view.suppression_reason}
                      outcomeWeight={view.outcome_weight}
                    />
                    {view.supporting_quote ? (
                      <div className="chat-memory-write-subcopy">
                        {view.supporting_quote}
                      </div>
                    ) : null}
                  </article>
                ))}
              </div>
            </section>
          ) : null}

          {trace?.evidence_hits?.length ? (
            <section className="chat-inspector-section">
              <header className="chat-inspector-section-header">
                <h3>{t("inspector.context.evidence")}</h3>
              </header>
              <div className="chat-inspector-card-list">
                {trace.evidence_hits.map((evidence) => (
                  <article key={evidence.id} className="chat-inspector-card">
                    <div className="chat-inspector-card-row">
                      {evidence.source_type ? (
                        <span className="chat-inspector-pill">
                          {evidence.source_type}
                        </span>
                      ) : null}
                      {formatRetrievalPercent(evidence.score) ? (
                        <span className="chat-inspector-metric">
                          {formatRetrievalPercent(evidence.score)}
                        </span>
                      ) : null}
                    </div>
                    <div className="chat-inspector-card-body">
                      {evidence.snippet || evidence.quote_text}
                    </div>
                    <TraceDiagnostics
                      t={t}
                      selectionReason={evidence.selection_reason ?? evidence.why_selected}
                      episodeIds={evidence.episode_id ? [evidence.episode_id] : []}
                    />
                  </article>
                ))}
              </div>
            </section>
          ) : null}

          {uiMode === "debug" && trace ? (
            <section
              className="chat-inspector-section"
              data-inspector-section="raw"
            >
              <header className="chat-inspector-section-header">
                <h3>{t("inspector.context.debug")}</h3>
              </header>
              <div className="chat-inspector-debug-grid">
                <div>{t("inspector.debug.strategy")}</div>
                <div>{trace.strategy || "n/a"}</div>
                <div>{t("inspector.debug.contextLevel")}</div>
                <div>{retrievalSummary?.contextLevel || "n/a"}</div>
                <div>{t("inspector.debug.decisionSource")}</div>
                <div>{trace.decision_source || "n/a"}</div>
                <div>{t("inspector.debug.confidence")}</div>
                <div>
                  {typeof trace.decision_confidence === "number"
                    ? `${Math.round(trace.decision_confidence * 100)}%`
                    : "n/a"}
                </div>
                <div>rerank</div>
                <div>
                  {typeof trace.rerank_latency_ms === "number"
                    ? `${Math.round(trace.rerank_latency_ms)} ms`
                    : "n/a"}
                </div>
              </div>
            </section>
          ) : null}

          {!message.sources?.length &&
          !memoryGroups.profile.length &&
          !memoryGroups.recent.length &&
          !trace?.view_hits?.length &&
          !trace?.evidence_hits?.length &&
          !trace?.knowledge_chunks.length &&
          !trace?.linked_file_chunks.length ? (
            <EmptyBody
              title={t("inspector.context.emptyTitle")}
              description={t("inspector.context.emptyDescription")}
            />
          ) : null}
        </div>
      ) : null}

      {inspectorState.tab === "memory_write" ? (
        <div className="chat-inspector-content">
          {message ? (
            <MemoryWriteTabContent
              key={`${message.id}:${inspectorState.tab}`}
              message={message}
              memorySummary={memorySummary}
              memoryWriteDetail={memoryWriteDetails[message.id] ?? null}
              memoryWriteStatus={memoryWriteStatuses[message.id] ?? "idle"}
              memoryDetails={memoryDetails}
              memoryStatuses={memoryStatuses}
              onEnsureMemoryDetail={onEnsureMemoryDetail}
              onUpdateMemory={onUpdateMemory}
              onDeleteMemory={onDeleteMemory}
              onPromoteMemory={onPromoteMemory}
            />
          ) : (
            <EmptyBody
              title={t("inspector.memory.emptyTitle")}
              description={t("inspector.memory.emptyDescription")}
            />
          )}
        </div>
      ) : null}

      {inspectorState.tab === "thinking" ? (
        <div className="chat-inspector-content">
          {thinkingSummary.content ? (
            <section className="chat-inspector-section">
              <p className="chat-inspector-note">
                {t("inspector.thinking.note")}
              </p>
              <pre className="chat-inspector-raw-block">
                {thinkingSummary.content}
              </pre>
            </section>
          ) : (
            <EmptyBody
              title={t("inspector.thinking.emptyTitle")}
              description={t("inspector.thinking.emptyDescription")}
            />
          )}
        </div>
      ) : null}

      {inspectorState.tab === "debug" ? (
        <div className="chat-inspector-content">
          {uiMode === "debug" ? (
            <section className="chat-inspector-section">
              <div className="chat-inspector-debug-grid">
                <div>{t("inspector.debug.sources")}</div>
                <div>{message.sources?.length ?? 0}</div>
                <div>{t("inspector.debug.memories")}</div>
                <div>{trace?.memories.length ?? 0}</div>
                <div>{t("inspector.debug.knowledge")}</div>
                <div>{trace?.knowledge_chunks.length ?? 0}</div>
                <div>{t("inspector.debug.files")}</div>
                <div>{trace?.linked_file_chunks.length ?? 0}</div>
              </div>
              <pre className="chat-inspector-raw-block">
                {JSON.stringify(message.metadataJson ?? {}, null, 2)}
              </pre>
            </section>
          ) : (
            <EmptyBody
              title={t("inspector.debug.emptyTitle")}
              description={t("inspector.debug.emptyDescription")}
            />
          )}
        </div>
      ) : null}
    </div>
  );

  return (
    <ConsoleInspectorPanel
      className="chat-inspector-panel"
      title={panelTitle}
      description={panelDescription}
      action={action}
    >
      {body}
    </ConsoleInspectorPanel>
  );
}

export function ConversationInspector({
  variant,
  inspectorState,
  onClose,
  ...props
}: ConversationInspectorProps) {
  const t = useTranslations("console-chat");

  if (!inspectorState.open) {
    return null;
  }

  if (variant === "sheet") {
    return (
      <Dialog open={inspectorState.open} onOpenChange={(open) => !open && onClose()}>
        <DialogContent className="chat-inspector-sheet">
          <DialogHeader className="chat-inspector-sheet-header sr-only">
            <DialogTitle>{t("inspector.context.title")}</DialogTitle>
            <DialogDescription>{t("inspector.context.description")}</DialogDescription>
          </DialogHeader>
          <InspectorInner
            {...props}
            inspectorState={inspectorState}
            onClose={onClose}
          />
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <div className={`chat-inspector-shell chat-inspector-shell--${variant}`}>
      <InspectorInner
        {...props}
        inspectorState={inspectorState}
        onClose={onClose}
      />
    </div>
  );
}
