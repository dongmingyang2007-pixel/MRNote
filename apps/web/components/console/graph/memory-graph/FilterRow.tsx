"use client";

import { useTranslations } from "next-intl";
import { ROLE_STYLE } from "./constants";
import type { Role } from "./types";

const ALL_ROLES: Role[] = ["fact", "structure", "subject", "concept", "summary"];

interface Props {
  search: string;
  confMin: number;
  filters: Record<Role, boolean>;
  counts: Record<Role, number>;
  compact?: boolean;
  onSearch: (value: string) => void;
  onConfMin: (value: number) => void;
  onToggleFilter: (role: Role) => void;
}

export function FilterRow(p: Props) {
  const t = useTranslations("console-notebooks");
  return (
    <div
      className="mg-filter-row"
      style={{
        display: "flex", alignItems: "center", gap: 10, padding: "8px 12px",
        borderBottom: "1px solid var(--border, rgba(15,42,45,0.08))",
        flexWrap: "wrap",
      }}
    >
      {!p.compact && (
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
      )}
      <div style={{ flex: 1 }} />
      <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
        {!p.compact && <span>{t("memoryGraph.confSlider.label")}</span>}
        <input
          data-testid="mg-conf-slider"
          type="range" min={0.6} max={0.99} step={0.01}
          value={p.confMin}
          onChange={(e) => p.onConfMin(Number(e.target.value))}
          style={{ width: p.compact ? 80 : 120 }}
        />
        <span style={{ minWidth: 30, fontFamily: "monospace" }}>{p.confMin.toFixed(2)}</span>
      </label>
      <input
        data-testid="mg-search-input"
        type="search"
        placeholder={t("memoryGraph.searchPlaceholder")}
        value={p.search}
        onChange={(e) => p.onSearch(e.target.value)}
        style={{
          flex: "0 1 200px", padding: "6px 10px", borderRadius: 8,
          border: "1px solid var(--border, rgba(15,42,45,0.1))",
          background: "var(--bg-raised, #fff)", fontSize: 13,
        }}
      />
    </div>
  );
}
