"use client";

import { useTranslations } from "next-intl";
import { MemoryIcon } from "./MemoryIcons";
import type { MemoryViewMode, FilterPill } from "./memory-types";

// ---------------------------------------------------------------------------
// Filter options
// ---------------------------------------------------------------------------

const FILTER_OPTIONS: { key: FilterPill; labelKey: string }[] = [
  { key: "all", labelKey: "memory.filterAll" },
  { key: "permanent", labelKey: "memory.filterPermanent" },
  { key: "temporary", labelKey: "memory.filterTemporary" },
  { key: "profile", labelKey: "memory.filterProfile" },
  { key: "episodic", labelKey: "memory.filterEpisodic" },
  { key: "playbook", labelKey: "memory.filterPlaybook" },
  { key: "stale", labelKey: "memory.filterStale" },
  { key: "conflict", labelKey: "memory.filterConflict" },
  { key: "pinned", labelKey: "memory.filterPinned" },
  { key: "summary", labelKey: "memory.filterSummary" },
];

// ---------------------------------------------------------------------------
// View mode definitions
// ---------------------------------------------------------------------------

const VIEW_MODES: { key: MemoryViewMode; icon: string; labelKey: string }[] = [
  { key: "cards", icon: "grid", labelKey: "memory.viewCards" },
  { key: "list", icon: "list", labelKey: "memory.viewList" },
  { key: "views", icon: "layers", labelKey: "memory.viewViews" },
  { key: "evidence", icon: "book", labelKey: "memory.viewEvidence" },
  { key: "learning", icon: "lightning", labelKey: "memory.viewLearning" },
  { key: "health", icon: "star", labelKey: "memory.viewHealth" },
  { key: "graph", icon: "graph", labelKey: "memory.viewGraph" },
  { key: "3d", icon: "sphere", labelKey: "memory.view3D" },
];

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface MemoryToolbarProps {
  title: string;
  count: number;
  view: MemoryViewMode;
  filter: FilterPill;
  onViewChange: (view: MemoryViewMode) => void;
  onFilterChange: (filter: FilterPill) => void;
  onNewMemory: () => void;
  onExport: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MemoryToolbar({
  title,
  count,
  view,
  filter,
  onViewChange,
  onFilterChange,
  onNewMemory,
  onExport,
}: MemoryToolbarProps) {
  const t = useTranslations("console");

  const showFilterBar = view !== "graph" && view !== "3d";

  return (
    <div>
      {/* ---- Toolbar row ---- */}
      <div className="mem-toolbar">
        <div className="mem-toolbar-left">
          <h2 className="mem-toolbar-title">{title}</h2>
          <span className="mem-toolbar-count">
            {count} {t("memory.countUnit")}
          </span>
        </div>

        <div className="mem-toolbar-spacer" />

        <div className="mem-view-switcher">
          {VIEW_MODES.map((mode) => (
            <button
              key={mode.key}
              type="button"
              className={`mem-view-btn${view === mode.key ? " is-active" : ""}`}
              title={t(mode.labelKey)}
              aria-label={t(mode.labelKey)}
              onClick={() => onViewChange(mode.key)}
            >
              <MemoryIcon name={mode.icon} width={16} height={16} />
            </button>
          ))}
        </div>

        <div className="mem-toolbar-actions">
          <button
            type="button"
            className="mem-action-btn"
            onClick={onExport}
            aria-label={t("memory.export")}
          >
            <MemoryIcon name="export" width={16} height={16} />
            {t("memory.export")}
          </button>

          <button
            type="button"
            className="mem-action-btn is-primary"
            onClick={onNewMemory}
          >
            <MemoryIcon name="plus" width={16} height={16} />
            {t("memory.new")}
          </button>
        </div>
      </div>

      {/* ---- Filter bar (cards / list only) ---- */}
      {showFilterBar && (
        <div className="mem-filter-bar">
          {FILTER_OPTIONS.map((opt) => (
            <button
              key={opt.key}
              type="button"
              className={`mem-filter-pill${filter === opt.key ? " is-active" : ""}`}
              onClick={() => onFilterChange(opt.key)}
            >
              {t(opt.labelKey)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
