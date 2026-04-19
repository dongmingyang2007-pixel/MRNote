"use client";

import { useTranslations } from "next-intl";
import { ROLE_STYLE } from "../constants";
import { ROLE_GLYPH } from "./constants3d";
import type { GraphNode } from "../types";

interface Props {
  node: GraphNode;
  x: number;
  y: number;
}

export function Tooltip3d({ node, x, y }: Props) {
  const t = useTranslations("console-notebooks");
  const style = ROLE_STYLE[node.role];
  return (
    <div
      data-testid="mg3d-tooltip"
      style={{
        position: "absolute", left: x, top: y - 14, transform: "translate(-50%, -100%)",
        display: "inline-flex", alignItems: "center", gap: 6, pointerEvents: "none",
        padding: "4px 8px", borderRadius: 8,
        background: "rgba(255,255,255,0.92)",
        backdropFilter: "blur(12px)",
        border: "1px solid rgba(15,42,45,0.1)",
        fontSize: 12, fontWeight: 500,
        color: "var(--text-primary, #0f172a)",
        whiteSpace: "nowrap", zIndex: 3,
      }}
    >
      <span style={{
        display: "inline-flex", alignItems: "center", gap: 4,
        padding: "1px 6px", borderRadius: 4, fontSize: 11,
        background: style.fill, color: style.text,
      }}>
        {ROLE_GLYPH[node.role]} {t(`memoryGraph.roles.${node.role}`)}
      </span>
      {node.label}
    </div>
  );
}
