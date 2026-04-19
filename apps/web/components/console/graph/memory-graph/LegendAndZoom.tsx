"use client";

import { useTranslations } from "next-intl";
import { Plus, Minus, Maximize2 } from "lucide-react";
import { ROLE_STYLE } from "./constants";
import type { Role } from "./types";

interface Props {
  zoom: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFit: () => void;
  /** Hide the legend overlay when the canvas is too narrow. Zoom controls always show. */
  showLegend?: boolean;
}

const ORDERED_ROLES: Role[] = ["fact", "structure", "subject", "concept", "summary"];

export function LegendAndZoom({ zoom, onZoomIn, onZoomOut, onFit, showLegend = true }: Props) {
  const t = useTranslations("console-notebooks");
  return (
    <>
      {showLegend && (
      <div
        className="mg-legend"
        style={{
          position: "absolute", top: 12, left: 12,
          background: "rgba(255,255,255,0.88)",
          backdropFilter: "blur(12px)",
          padding: "10px 12px", borderRadius: 10,
          border: "1px solid rgba(15,42,45,0.1)",
          fontSize: 12, lineHeight: 1.5, zIndex: 2,
        }}
      >
        <div style={{ fontWeight: 600, marginBottom: 6 }}>
          {t("memoryGraph.legend.title")}
        </div>
        {ORDERED_ROLES.map((r) => (
          <div key={r} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span
              aria-hidden="true"
              style={{
                width: 10, height: 10, borderRadius: "50%",
                background: ROLE_STYLE[r].dot, display: "inline-block",
              }}
            />
            {t(`memoryGraph.roles.${r}`)}
          </div>
        ))}
      </div>
      )}
      <div
        className="mg-zoom"
        style={{
          position: "absolute", bottom: 12, left: 12,
          background: "rgba(255,255,255,0.88)",
          backdropFilter: "blur(12px)",
          padding: 6, borderRadius: 10,
          border: "1px solid rgba(15,42,45,0.1)",
          display: "flex", alignItems: "center", gap: 4, zIndex: 2,
        }}
      >
        <button type="button" onClick={onZoomOut} data-testid="mg-zoom-out"
          aria-label="Zoom out" style={{ padding: 4 }}>
          <Minus size={14} />
        </button>
        <span data-testid="mg-zoom-indicator" style={{ minWidth: 42, textAlign: "center", fontSize: 12 }}>
          {Math.round(zoom * 100)}%
        </span>
        <button type="button" onClick={onZoomIn} data-testid="mg-zoom-in"
          aria-label="Zoom in" style={{ padding: 4 }}>
          <Plus size={14} />
        </button>
        <button type="button" onClick={onFit} data-testid="mg-zoom-fit"
          aria-label="Fit" style={{ padding: 4 }}>
          <Maximize2 size={14} />
        </button>
      </div>
    </>
  );
}
