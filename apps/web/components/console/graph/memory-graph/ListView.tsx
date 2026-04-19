"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { ROLE_STYLE } from "./constants";
import type { GraphNode } from "./types";

type SortKey = "label" | "role" | "conf" | "reuse" | "lastUsed";
type SortDir = "asc" | "desc";

interface Props {
  nodes: GraphNode[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function ListView({ nodes, selectedId, onSelect }: Props) {
  const t = useTranslations("console-notebooks");
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir } | null>(null);

  const sorted = useMemo(() => {
    if (!sort) return nodes;
    const arr = [...nodes];
    arr.sort((a, b) => {
      let av: string | number = "";
      let bv: string | number = "";
      switch (sort.key) {
        case "label": av = a.label; bv = b.label; break;
        case "role": av = a.role; bv = b.role; break;
        case "conf": av = a.conf; bv = b.conf; break;
        case "reuse": av = a.reuse; bv = b.reuse; break;
        case "lastUsed": av = a.lastUsed ?? ""; bv = b.lastUsed ?? ""; break;
      }
      if (av < bv) return sort.dir === "asc" ? -1 : 1;
      if (av > bv) return sort.dir === "asc" ? 1 : -1;
      return 0;
    });
    return arr;
  }, [nodes, sort]);

  const clickHeader = (key: SortKey) => {
    setSort((prev) => {
      if (!prev || prev.key !== key) return { key, dir: "desc" };
      return { key, dir: prev.dir === "desc" ? "asc" : "desc" };
    });
  };

  const headers: Array<{ key: SortKey; id: string }> = [
    { key: "label", id: "label" },
    { key: "role", id: "role" },
    { key: "conf", id: "conf" },
    { key: "reuse", id: "reuse" },
    { key: "lastUsed", id: "lastUsed" },
  ];

  return (
    <div style={{ height: "100%", overflow: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead style={{ position: "sticky", top: 0, background: "var(--bg-surface, #fff)", zIndex: 1 }}>
          <tr>
            {headers.map((h) => (
              <th
                key={h.key}
                data-testid={`mg-list-header-${h.id}`}
                onClick={() => clickHeader(h.key)}
                style={{
                  textAlign: "left", padding: "8px 10px",
                  borderBottom: "1px solid var(--border, rgba(15,42,45,0.08))",
                  fontWeight: 600, cursor: "pointer", userSelect: "none",
                }}
              >
                {t(`memoryGraph.list.columns.${h.id}`)}
                {sort?.key === h.key ? (sort.dir === "asc" ? " ▲" : " ▼") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((n) => {
            const selected = n.id === selectedId;
            const style = ROLE_STYLE[n.role];
            return (
              <tr
                key={n.id}
                data-testid={`mg-list-row-${n.id}`}
                onClick={() => onSelect(n.id)}
                aria-selected={selected}
                style={{
                  cursor: "pointer",
                  background: selected ? "rgba(13,148,136,0.08)" : undefined,
                }}
              >
                <td style={{ padding: "6px 10px" }}>{n.label}</td>
                <td style={{ padding: "6px 10px" }}>
                  <span style={{
                    padding: "2px 6px", borderRadius: 4, fontSize: 11,
                    background: style.fill, color: style.text, border: `1px solid ${style.stroke}`,
                  }}>
                    {t(`memoryGraph.roles.${n.role}`)}
                  </span>
                </td>
                <td style={{ padding: "6px 10px", fontFamily: "monospace" }}>{n.conf.toFixed(2)}</td>
                <td style={{ padding: "6px 10px", fontFamily: "monospace" }}>{n.reuse}</td>
                <td style={{ padding: "6px 10px", color: "var(--text-secondary)" }}>{n.lastUsed ?? "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
