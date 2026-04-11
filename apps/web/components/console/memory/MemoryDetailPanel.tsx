"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useTranslations } from "next-intl";
import { apiGet } from "@/lib/api";
import {
  CloseIcon,
  EditIcon,
  ArrowUpIcon,
  TrashIcon,
  ChevronRightIcon,
} from "./MemoryIcons";
import type { MemoryDetailTab, MemoryNode } from "./memory-types";
import type { MemoryEdge } from "@/hooks/useGraphData";
import {
  isPinnedMemoryNode,
  isSummaryMemoryNode,
  getMemoryRetrievalCount,
  getMemoryCategoryLabel,
  getMemorySalience,
} from "@/hooks/useGraphData";

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function formatPercent(value?: number | null): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "--";
  }
  return `${Math.round(value * 100)}%`;
}

function mergeDetailWithNode(
  node: MemoryNode,
  detail: MemoryDetailResponse | null,
): MemoryDetailResponse {
  const fallback: MemoryDetailResponse = {
    id: node.id,
    content: node.content,
    category: node.category,
    type: node.type,
  };
  const base = detail ?? fallback;
  return {
    ...base,
    id: node.id,
    content: node.content,
    category: node.category,
    type: node.type,
    confidence: node.confidence ?? base.confidence,
    observed_at: node.observed_at ?? base.observed_at,
    valid_from: node.valid_from ?? base.valid_from,
    valid_to: node.valid_to ?? base.valid_to,
    last_confirmed_at: node.last_confirmed_at ?? base.last_confirmed_at,
    suppression_reason: node.suppression_reason ?? base.suppression_reason,
    reconfirm_after: node.reconfirm_after ?? base.reconfirm_after,
    last_used_at: node.last_used_at ?? base.last_used_at,
    reuse_success_rate: node.reuse_success_rate ?? base.reuse_success_rate,
    evidences: base.evidences,
    episodes: base.episodes,
    views: base.views,
    timeline_events: base.timeline_events,
    write_history: base.write_history,
    learning_history: base.learning_history,
  };
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface MemoryDetailPanelProps {
  node: MemoryNode;
  allNodes: MemoryNode[];
  edges: MemoryEdge[];
  onClose: () => void;
  onUpdate: (id: string, content: string, category?: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onPromote: (id: string) => Promise<void>;
  onSelect: (id: string, detailTab?: MemoryDetailTab) => void;
  initialTab?: MemoryDetailTab;
}

interface MemoryDetailResponse {
  id: string;
  content: string;
  category: string;
  type: "permanent" | "temporary";
  confidence?: number | null;
  observed_at?: string | null;
  valid_from?: string | null;
  valid_to?: string | null;
  last_confirmed_at?: string | null;
  suppression_reason?: string | null;
  reconfirm_after?: string | null;
  last_used_at?: string | null;
  reuse_success_rate?: number | null;
  evidences?: Array<{
    id: string;
    quote_text: string;
    source_type?: string | null;
    confidence?: number | null;
    created_at?: string | null;
  }>;
  episodes?: Array<{
    id: string;
    source_type: string;
    chunk_text: string;
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
  learning_history?: Array<{
    id: string;
    trigger?: string | null;
    status?: string | null;
    stages?: string[] | null;
    created_at?: string | null;
  }>;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MemoryDetailPanel({
  node,
  allNodes,
  edges,
  onClose,
  onUpdate,
  onDelete,
  onPromote,
  onSelect,
  initialTab = "evidence",
}: MemoryDetailPanelProps) {
  const t = useTranslations("console");
  const panelRef = useRef<HTMLDivElement>(null);

  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState(node.content);
  const [detail, setDetail] = useState<MemoryDetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailTab, setDetailTab] = useState<MemoryDetailTab>(initialTab);

  useEffect(() => {
    setDetailTab(initialTab);
  }, [initialTab]);

  useEffect(() => {
    let cancelled = false;
    const loadDetail = async () => {
      setDetailLoading(true);
      try {
        const response = await apiGet<MemoryDetailResponse | { node?: MemoryDetailResponse }>(
          `/api/v1/memory/${node.id}`,
        );
        if (cancelled) {
          return;
        }
        const payload =
          response && typeof response === "object" && "node" in response
            ? response.node || null
            : response;
        setDetail((payload as MemoryDetailResponse | null) ?? null);
      } catch {
        if (!cancelled) {
          setDetail(null);
        }
      } finally {
        if (!cancelled) {
          setDetailLoading(false);
        }
      }
    };
    void loadDetail();
    return () => {
      cancelled = true;
    };
  }, [node.id, node.updated_at]);

  // Click-outside to close
  useEffect(() => {
    function handleMouseDown(e: MouseEvent) {
      if (
        panelRef.current &&
        !panelRef.current.contains(e.target as Node)
      ) {
        onClose();
      }
    }
    document.addEventListener("mousedown", handleMouseDown);
    return () => document.removeEventListener("mousedown", handleMouseDown);
  }, [onClose]);

  // ---- Edit handlers -------------------------------------------------------

  const handleSave = useCallback(async () => {
    await onUpdate(node.id, editContent);
    setDetail((prev) =>
      prev
        ? {
            ...prev,
            content: editContent,
          }
        : prev,
    );
    setIsEditing(false);
  }, [node.id, editContent, onUpdate]);

  const handleCancel = useCallback(() => {
    setEditContent(node.content);
    setIsEditing(false);
  }, [node.content]);

  // ---- Related memories ----------------------------------------------------

  const relatedItems = edges
    .filter(
      (e) =>
        e.source_memory_id === node.id || e.target_memory_id === node.id,
    )
    .map((e) => {
      const connectedId =
        e.source_memory_id === node.id
          ? e.target_memory_id
          : e.source_memory_id;
      const connectedNode = allNodes.find((n) => n.id === connectedId);
      return connectedNode ? { edge: e, node: connectedNode } : null;
    })
    .filter(Boolean) as { edge: MemoryEdge; node: MemoryNode }[];

  // ---- Derived data --------------------------------------------------------

  const pinned = isPinnedMemoryNode(node);
  const summary = isSummaryMemoryNode(node);
  const retrievalCount = getMemoryRetrievalCount(node);
  const salience = getMemorySalience(node);
  const categoryLabel = getMemoryCategoryLabel(node) || node.category;
  const activeDetail = mergeDetailWithNode(node, detail);

  // ---- Render --------------------------------------------------------------

  return (
    <div className="mem-detail" ref={panelRef}>
      {/* Header */}
      <div className="mem-detail-header">
        <h2>{t("memory.detailTitle")}</h2>
        <button
          className="mem-detail-close"
          onClick={onClose}
          aria-label="Close"
        >
          <CloseIcon width={18} height={18} />
        </button>
      </div>

      {/* Scrollable body */}
      <div className="mem-detail-body">
        {/* Content (read / edit) */}
        {isEditing ? (
          <div className="mem-detail-section">
            <textarea
              className="mem-detail-edit-area"
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              rows={6}
              autoFocus
            />
            <div className="mem-detail-edit-actions">
              <button
                className="mem-action-btn is-primary"
                onClick={handleSave}
              >
                {t("memory.save")}
              </button>
              <button className="mem-action-btn" onClick={handleCancel}>
                {t("memory.cancel")}
              </button>
            </div>
          </div>
        ) : (
          <div className="mem-detail-content">{activeDetail.content}</div>
        )}

        {/* Category */}
        <div className="mem-detail-section">
          <div className="mem-detail-section-title">
            {t("memory.detailCategory")}
          </div>
          <span className="mem-detail-category">{categoryLabel}</span>
        </div>

        {/* Badges */}
        <div className="mem-detail-section">
          <div className="mem-detail-badges">
            {activeDetail.type === "permanent" ? (
              <span className="mem-badge is-permanent">
                {t("memory.badgePermanent")}
              </span>
            ) : (
              <span className="mem-badge is-temporary">
                {t("memory.badgeTemporary")}
              </span>
            )}
            {pinned && (
              <span className="mem-badge is-pinned">
                {t("memory.badgePinned")}
              </span>
            )}
            {summary && (
              <span className="mem-badge is-summary">
                {t("memory.badgeSummary")}
              </span>
            )}
          </div>
        </div>

        {/* Statistics - 2x2 grid */}
        <div className="mem-detail-section">
          <div className="mem-detail-stats">
            <div className="mem-detail-stat">
              <span className="mem-detail-stat-label">
                {t("memory.statRetrieval")}
              </span>
              <span className="mem-detail-stat-value">{retrievalCount}</span>
            </div>
            <div className="mem-detail-stat">
              <span className="mem-detail-stat-label">
                {t("memory.statImportance")}
              </span>
              <span className="mem-detail-stat-value">
                {salience !== null ? salience.toFixed(2) : "--"}
              </span>
            </div>
            <div className="mem-detail-stat">
              <span className="mem-detail-stat-label">
                {t("memory.statLastUsed")}
              </span>
              <span className="mem-detail-stat-value">
                {activeDetail.last_used_at ? formatDate(activeDetail.last_used_at) : "--"}
                {detailLoading ? " · ..." : ""}
              </span>
            </div>
            <div className="mem-detail-stat">
              <span className="mem-detail-stat-label">
                {t("memory.statCreated")}
              </span>
              <span className="mem-detail-stat-value">
                {formatDate(node.created_at)}
              </span>
            </div>
          </div>
        </div>

        <div className="mem-detail-section">
          <div className="mem-detail-section-title">
            {t("memory.detailTimeValidity")}
          </div>
          <div className="mem-detail-stats">
            <div className="mem-detail-stat">
              <span className="mem-detail-stat-label">
                {t("memory.detailConfidence")}
              </span>
              <span className="mem-detail-stat-value">
                {typeof activeDetail.confidence === "number"
                  ? activeDetail.confidence.toFixed(2)
                  : "--"}
              </span>
            </div>
            <div className="mem-detail-stat">
              <span className="mem-detail-stat-label">
                {t("memory.detailObserved")}
              </span>
              <span className="mem-detail-stat-value">
                {activeDetail.observed_at ? formatDate(activeDetail.observed_at) : "--"}
              </span>
            </div>
            <div className="mem-detail-stat">
              <span className="mem-detail-stat-label">
                {t("memory.detailValidFrom")}
              </span>
              <span className="mem-detail-stat-value">
                {activeDetail.valid_from ? formatDate(activeDetail.valid_from) : "--"}
              </span>
            </div>
            <div className="mem-detail-stat">
              <span className="mem-detail-stat-label">
                {t("memory.detailValidTo")}
              </span>
              <span className="mem-detail-stat-value">
                {activeDetail.valid_to ? formatDate(activeDetail.valid_to) : "--"}
              </span>
            </div>
            <div className="mem-detail-stat">
              <span className="mem-detail-stat-label">
                {t("memory.detailConfirmed")}
              </span>
              <span className="mem-detail-stat-value">
                {activeDetail.last_confirmed_at
                  ? formatDate(activeDetail.last_confirmed_at)
                  : "--"}
              </span>
            </div>
            <div className="mem-detail-stat">
              <span className="mem-detail-stat-label">
                {t("memory.detailReconfirmAfter")}
              </span>
              <span className="mem-detail-stat-value">
                {activeDetail.reconfirm_after
                  ? formatDate(activeDetail.reconfirm_after)
                  : "--"}
              </span>
            </div>
            <div className="mem-detail-stat">
              <span className="mem-detail-stat-label">
                {t("memory.detailReuseRate")}
              </span>
              <span className="mem-detail-stat-value">
                {formatPercent(activeDetail.reuse_success_rate)}
              </span>
            </div>
          </div>
          {activeDetail.suppression_reason ? (
            <>
              <div className="mem-detail-section-title">
                {t("memory.detailSuppressionReason")}
              </div>
              <div className="mem-detail-content">
                {activeDetail.suppression_reason}
              </div>
            </>
          ) : null}
        </div>

        {/* Source conversation */}
        {node.source_conversation_id && (
          <div className="mem-detail-section">
            <div className="mem-detail-section-title">
              {t("memory.sourceConversation")}
            </div>
            <a
              className="mem-detail-source"
              href={`/console/conversations/${node.source_conversation_id}`}
            >
              {node.source_conversation_id}
              <ChevronRightIcon width={14} height={14} />
            </a>
          </div>
        )}

        {/* Related memories */}
        <div className="mem-detail-section">
          <div className="mem-detail-section-title">
            {t("memory.relatedMemories")}
          </div>
          {relatedItems.length > 0 ? (
            <div className="mem-detail-related">
              {relatedItems.map(({ edge, node: related }) => (
                <button
                  key={edge.id}
                  className="mem-detail-related-item"
                  onClick={() => onSelect(related.id)}
                >
                  <span>
                    {related.content.length > 80
                      ? related.content.slice(0, 80) + "..."
                      : related.content}
                  </span>
                  <ChevronRightIcon width={14} height={14} />
                </button>
              ))}
            </div>
          ) : (
            <p className="mem-detail-empty">{t("memory.noRelated")}</p>
          )}
        </div>

        <div className="mem-detail-section">
          <div className="mem-detail-section-title">
            {t("memory.detailDetails")}
          </div>
          <div className="mem-detail-badges" style={{ marginBottom: 12 }}>
            {([
              ["evidence", t("memory.detailTabEvidence")],
              ["views", t("memory.detailTabViews")],
              ["timeline", t("memory.detailTabTimeline")],
              ["history", t("memory.detailTabHistory")],
              ["learning", t("memory.detailTabLearning")],
            ] as const).map(([key, label]) => (
              <button
                key={key}
                type="button"
                className={`mem-action-btn ${detailTab === key ? "is-primary" : ""}`}
                onClick={() => setDetailTab(key)}
              >
                {label}
              </button>
            ))}
          </div>

          {detailTab === "evidence" ? (
            activeDetail.evidences?.length || activeDetail.episodes?.length ? (
              <>
                {activeDetail.evidences?.length ? (
                  <div className="mem-detail-related">
                    {activeDetail.evidences.map((evidence) => (
                      <div key={evidence.id} className="mem-detail-related-item" style={{ cursor: "default" }}>
                        <span>
                          {evidence.quote_text}
                          {typeof evidence.confidence === "number"
                            ? ` (${evidence.confidence.toFixed(2)})`
                            : ""}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : null}
                {activeDetail.episodes?.length ? (
                  <>
                    <div className="mem-detail-section-title" style={{ marginTop: 8 }}>
                      {t("memory.detailEpisodes")}
                    </div>
                    <div className="mem-detail-related">
                      {activeDetail.episodes.map((episode) => (
                        <div key={episode.id} className="mem-detail-related-item" style={{ cursor: "default" }}>
                          <span>
                            {episode.source_type}
                            {episode.created_at ? ` · ${formatDate(episode.created_at)}` : ""}
                            {episode.chunk_text ? ` · ${episode.chunk_text}` : ""}
                          </span>
                        </div>
                      ))}
                    </div>
                  </>
                ) : null}
              </>
            ) : (
              <p className="mem-detail-empty">{t("memory.detailNoEvidence")}</p>
            )
          ) : null}

          {detailTab === "views" ? (
            activeDetail.views?.length ? (
              <div className="mem-detail-related">
                {activeDetail.views.map((view) => (
                  <div key={view.id} className="mem-detail-related-item" style={{ cursor: "default" }}>
                    <span>{view.view_type ? `[${view.view_type}] ` : ""}{view.content}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mem-detail-empty">{t("memory.detailNoViews")}</p>
            )
          ) : null}

          {detailTab === "timeline" ? (
            activeDetail.timeline_events?.length ? (
              <div className="mem-detail-related">
                {activeDetail.timeline_events.map((event) => (
                  <div key={event.id} className="mem-detail-related-item" style={{ cursor: "default" }}>
                    <span>
                      {event.content}
                      {event.observed_at ? ` · ${formatDate(event.observed_at)}` : ""}
                      {event.node_status ? ` · ${event.node_status}` : ""}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mem-detail-empty">{t("memory.detailNoTimeline")}</p>
            )
          ) : null}

          {detailTab === "history" ? (
            activeDetail.write_history?.length ? (
              <div className="mem-detail-related">
                {activeDetail.write_history.map((item) => (
                  <div key={item.id} className="mem-detail-related-item" style={{ cursor: "default" }}>
                    <span>
                      {item.decision || "write"}
                      {item.reason ? ` · ${item.reason}` : ""}
                      {item.created_at ? ` · ${formatDate(item.created_at)}` : ""}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mem-detail-empty">{t("memory.detailNoWriteHistory")}</p>
            )
          ) : null}

          {detailTab === "learning" ? (
            activeDetail.learning_history?.length ? (
              <div className="mem-detail-related">
                {activeDetail.learning_history.map((item) => (
                  <div key={item.id} className="mem-detail-related-item" style={{ cursor: "default" }}>
                    <span>
                      {(item.trigger || "post_turn").replace(/_/g, " ")}
                      {item.status ? ` · ${item.status}` : ""}
                      {item.stages?.length
                        ? ` · ${item.stages.join(" -> ")}`
                        : ` · ${t("memory.noLearningStages")}`}
                      {item.created_at ? ` · ${formatDate(item.created_at)}` : ""}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mem-detail-empty">{t("memory.detailNoLearningHistory")}</p>
            )
          ) : null}
        </div>
      </div>

      {/* Action bar (fixed at bottom) */}
      <div className="mem-detail-actions">
        <button
          className="mem-action-btn is-primary"
          onClick={() => {
            setEditContent(node.content);
            setIsEditing(true);
          }}
        >
          <EditIcon width={16} height={16} />
          {t("memory.edit")}
        </button>
        {activeDetail.type === "temporary" && (
          <button
            className="mem-action-btn is-primary"
            onClick={() => onPromote(node.id)}
          >
            <ArrowUpIcon width={16} height={16} />
            {t("memory.promote")}
          </button>
        )}
        <button
          className="mem-action-btn is-danger"
          onClick={() => onDelete(node.id)}
        >
          <TrashIcon width={16} height={16} />
          {t("memory.delete")}
        </button>
      </div>
    </div>
  );
}
