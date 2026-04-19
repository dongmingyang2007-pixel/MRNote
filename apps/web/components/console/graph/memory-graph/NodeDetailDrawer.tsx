"use client";

import { useTranslations } from "next-intl";
import { X, Pin } from "lucide-react";
import { ROLE_STYLE } from "./constants";
import type { GraphNode } from "./types";

export interface DrawerNeighbor {
  id: string;
  rel: string;
  node: GraphNode;
}

interface Props {
  node: GraphNode;
  neighbors: DrawerNeighbor[];
  onSelectNeighbor: (id: string) => void;
  onClose: () => void;
}

const LIFECYCLE_STAGES: ReadonlyArray<{ id: string; done: boolean }> = [
  { id: "observe",     done: true  },
  { id: "consolidate", done: true  },
  { id: "reuse",       done: true  },
  { id: "reinforce",   done: false },
];

export function NodeDetailDrawer({ node, neighbors, onSelectNeighbor, onClose }: Props) {
  const t = useTranslations("console-notebooks");
  const style = ROLE_STYLE[node.role];
  const summary = node.raw?.content ?? "";

  return (
    <aside
      role="complementary"
      aria-label="Node detail"
      className="mg-drawer"
      style={{
        width: 300, height: "100%", flexShrink: 0,
        background: "var(--bg-surface, #fff)",
        borderLeft: "1px solid var(--border, rgba(15,42,45,0.08))",
        padding: 16, overflowY: "auto", fontSize: 13, lineHeight: 1.5,
        display: "flex", flexDirection: "column", gap: 12,
      }}
    >
      <header style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          style={{
            padding: "2px 8px", borderRadius: 999, fontSize: 11, fontWeight: 600,
            background: style.fill, color: style.text, border: `1px solid ${style.stroke}`,
          }}
        >
          {t(`memoryGraph.roles.${node.role}`)}
        </span>
        {node.pinned && (
          <span aria-label={t("memoryGraph.drawer.pinned")} title={t("memoryGraph.drawer.pinned")}
            style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, color: "#f97316" }}>
            <Pin size={12} />
            {t("memoryGraph.drawer.pinned")}
          </span>
        )}
        <div style={{ flex: 1 }} />
        <span style={{ fontFamily: "monospace", fontSize: 12, color: "var(--text-secondary)" }}>
          {node.conf.toFixed(2)}
        </span>
        <button aria-label="Close" onClick={onClose} type="button"
          style={{ padding: 2, background: "transparent", border: "none", cursor: "pointer" }}>
          <X size={14} />
        </button>
      </header>

      <h2 style={{ fontSize: 14, fontWeight: 700, margin: 0, color: "var(--text-primary)" }}>{node.label}</h2>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 6 }}>
        <MetaBlock label={t("memoryGraph.drawer.meta.source")} value={node.source ?? "—"} />
        <MetaBlock label={t("memoryGraph.drawer.meta.reuse")} value={String(node.reuse)} />
        <MetaBlock label={t("memoryGraph.drawer.meta.lastUsed")} value={node.lastUsed ?? "—"} />
      </div>

      <div aria-label="Confidence bar" style={{ height: 4, borderRadius: 2, background: "rgba(15,42,45,0.08)" }}>
        <div style={{ width: `${Math.round(node.conf * 100)}%`, height: "100%", borderRadius: 2, background: style.stroke }} />
      </div>

      <section>
        <SectionLabel>{t("memoryGraph.drawer.summary")}</SectionLabel>
        <p style={{ margin: 0, color: "var(--text-primary)" }}>{summary}</p>
      </section>

      <section>
        <SectionLabel>
          {t("memoryGraph.drawer.neighbors")} {neighbors.length}
        </SectionLabel>
        {neighbors.length === 0 && (
          <p style={{ margin: 0, color: "var(--text-secondary)" }}>—</p>
        )}
        {neighbors.map((n) => {
          const nStyle = ROLE_STYLE[n.node.role];
          return (
            <button
              key={n.id}
              data-testid={`mg-drawer-neighbor-${n.id}`}
              type="button"
              onClick={() => onSelectNeighbor(n.id)}
              style={{
                display: "flex", width: "100%", alignItems: "center", gap: 6,
                padding: "4px 0", background: "transparent", border: "none",
                cursor: "pointer", textAlign: "left", fontSize: 12,
              }}
            >
              <span style={{
                fontFamily: "monospace", fontSize: 10, color: "var(--text-secondary)",
                border: "1px solid var(--border, rgba(15,42,45,0.12))",
                padding: "0 4px", borderRadius: 4,
              }}>
                {n.rel}
              </span>
              <span aria-hidden style={{
                width: 8, height: 8, borderRadius: "50%", background: nStyle.dot,
              }} />
              <span>{n.node.label}</span>
            </button>
          );
        })}
      </section>

      <section>
        <SectionLabel>{t("memoryGraph.drawer.lifecycle")}</SectionLabel>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {LIFECYCLE_STAGES.map((s) => (
            <div
              key={s.id}
              data-testid={`mg-lifecycle-stage-${s.id}${s.done ? "-done" : ""}`}
              style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4, flex: 1 }}
            >
              <span style={{
                width: 10, height: 10, borderRadius: "50%",
                background: s.done ? "#0d9488" : "transparent",
                border: `1.5px solid #0d9488`,
              }} />
              <span style={{ fontSize: 10, color: "var(--text-secondary)" }}>
                {t(`memoryGraph.drawer.lifecycle.${s.id}`)}
              </span>
            </div>
          ))}
        </div>
      </section>
    </aside>
  );
}

function MetaBlock({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      padding: 8, borderRadius: 8, background: "rgba(15,42,45,0.04)",
      display: "flex", flexDirection: "column", gap: 2,
    }}>
      <span style={{ fontSize: 10, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 0.4 }}>
        {label}
      </span>
      <span style={{ fontSize: 13, fontWeight: 500, color: "var(--text-primary)" }}>{value}</span>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: 10, fontWeight: 600, letterSpacing: 0.6,
      textTransform: "uppercase", color: "var(--text-secondary)", marginBottom: 6,
    }}>
      {children}
    </div>
  );
}
