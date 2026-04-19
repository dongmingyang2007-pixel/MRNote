"use client";

import { useTranslations } from "next-intl";
import { RotateCcw, Maximize2 } from "lucide-react";
import { ROLE_STYLE } from "./constants";
import type { Role } from "./types";

const ALL_ROLES: Role[] = ["fact", "structure", "subject", "concept", "summary"];

interface Props {
  search: string;
  confMin: number;
  filters: Record<Role, boolean>;
  view: "graph" | "list";
  counts: Record<Role, number>;
  onSearch: (value: string) => void;
  onConfMin: (value: number) => void;
  onToggleFilter: (role: Role) => void;
  onRearrange: () => void;
  onFit: () => void;
  onViewChange: (view: "graph" | "list") => void;
}

export function Toolbar(p: Props) {
  const t = useTranslations("console-notebooks");
  return (
    <div
      className="mg-toolbar"
      style={{
        display: "flex", alignItems: "center", gap: 10, padding: "8px 12px",
        borderBottom: "1px solid var(--border, rgba(15,42,45,0.08))",
        flexWrap: "wrap",
      }}
    >
      <input
        data-testid="mg-search-input"
        type="search"
        placeholder={t("memoryGraph.searchPlaceholder")}
        value={p.search}
        onChange={(e) => p.onSearch(e.target.value)}
        style={{
          flex: "0 1 220px", padding: "6px 10px", borderRadius: 8,
          border: "1px solid var(--border, rgba(15,42,45,0.1))",
          background: "var(--bg-raised, #fff)", fontSize: 13,
        }}
      />
      <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
        <span>{t("memoryGraph.confSlider.label")}</span>
        <input
          data-testid="mg-conf-slider"
          type="range" min={0.6} max={0.99} step={0.01}
          value={p.confMin}
          onChange={(e) => p.onConfMin(Number(e.target.value))}
          style={{ width: 120 }}
        />
        <span style={{ minWidth: 30, fontFamily: "monospace" }}>{p.confMin.toFixed(2)}</span>
      </label>
      <div style={{ display: "flex", gap: 4 }}>
        {ALL_ROLES.map((r) => {
          const on = p.filters[r];
          const style = ROLE_STYLE[r];
          return (
            <button
              key={r}
              data-testid={`mg-chip-${r}`}
              type="button"
              onClick={() => p.onToggleFilter(r)}
              aria-pressed={on}
              style={{
                padding: "4px 10px", borderRadius: 999, fontSize: 12, fontWeight: 500,
                border: `1px solid ${on ? style.stroke : "rgba(15,42,45,0.15)"}`,
                background: on ? style.fill : "transparent",
                color: on ? style.text : "var(--text-secondary)",
                opacity: on ? 1 : 0.55,
                cursor: "pointer",
              }}
            >
              <span aria-hidden="true" style={{
                display: "inline-block", width: 6, height: 6, borderRadius: "50%",
                background: style.dot, marginRight: 6, verticalAlign: "middle",
              }} />
              {t(`memoryGraph.roles.${r}`)} <span style={{ opacity: 0.65 }}>{p.counts[r]}</span>
            </button>
          );
        })}
      </div>
      <div style={{ flex: 1 }} />
      <button data-testid="mg-btn-rearrange" type="button" onClick={p.onRearrange}
        style={{ padding: "4px 8px", fontSize: 12 }}>
        <RotateCcw size={12} style={{ marginRight: 4, verticalAlign: "middle" }} />
        {t("memoryGraph.rearrange")}
      </button>
      <button data-testid="mg-btn-fit" type="button" onClick={p.onFit}
        style={{ padding: "4px 8px", fontSize: 12 }}>
        <Maximize2 size={12} style={{ marginRight: 4, verticalAlign: "middle" }} />
        {t("memoryGraph.fit")}
      </button>
      <div role="tablist" style={{ display: "flex", gap: 2, marginLeft: 6 }}>
        <button
          data-testid="mg-btn-view-graph"
          type="button" role="tab" aria-selected={p.view === "graph"}
          onClick={() => p.onViewChange("graph")}
          style={{ padding: "4px 10px", fontSize: 12, fontWeight: p.view === "graph" ? 600 : 400 }}
        >
          {t("memoryGraph.view.graph")}
        </button>
        <button
          data-testid="mg-btn-view-list"
          type="button" role="tab" aria-selected={p.view === "list"}
          onClick={() => p.onViewChange("list")}
          style={{ padding: "4px 10px", fontSize: 12, fontWeight: p.view === "list" ? 600 : 400 }}
        >
          {t("memoryGraph.view.list")}
        </button>
      </div>
    </div>
  );
}
