"use client";

import { useTranslations } from "next-intl";
import { Network, Activity, ListTree } from "lucide-react";

export type MemoryGraphView = "graph" | "3d" | "list";

interface TabDef {
  id: MemoryGraphView;
  Icon: typeof Network;
  labelKey: string;
}

const TABS: TabDef[] = [
  { id: "graph", Icon: Network, labelKey: "memoryGraph.view.graph" },
  { id: "3d", Icon: Activity, labelKey: "memoryGraph.view.3d" },
  { id: "list", Icon: ListTree, labelKey: "memoryGraph.view.list" },
];

interface Props {
  view: MemoryGraphView;
  totalCount: number;
  onViewChange: (view: MemoryGraphView) => void;
}

export function ViewBar({ view, totalCount, onViewChange }: Props) {
  const t = useTranslations("console-notebooks");
  return (
    <div
      role="tablist"
      className="mg-view-bar"
      style={{
        display: "flex", alignItems: "center", gap: 2, padding: "4px 12px",
        borderBottom: "1px solid var(--border, rgba(15,42,45,0.08))",
      }}
    >
      {TABS.map((tab) => {
        const active = view === tab.id;
        return (
          <button
            key={tab.id}
            data-testid={`mg-btn-view-${tab.id}`}
            type="button" role="tab" aria-selected={active}
            onClick={() => onViewChange(tab.id)}
            style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              padding: "6px 12px", fontSize: 12,
              fontWeight: active ? 600 : 500,
              color: active ? "var(--accent, #0d9488)" : "var(--text-secondary, #64748b)",
              borderBottom: `2px solid ${active ? "var(--accent, #0d9488)" : "transparent"}`,
              background: "transparent", cursor: "pointer",
            }}
          >
            <tab.Icon size={13} strokeWidth={active ? 2 : 1.7} />
            {t(tab.labelKey)}
            <span style={{
              background: active ? "rgba(13,148,136,0.14)" : "rgba(15,42,45,0.06)",
              color: active ? "var(--accent, #0d9488)" : "var(--text-secondary, #64748b)",
              padding: "1px 6px", borderRadius: 999, fontSize: 11, fontWeight: 600,
              fontFeatureSettings: '"tnum"',
            }}>{totalCount}</span>
          </button>
        );
      })}
    </div>
  );
}
