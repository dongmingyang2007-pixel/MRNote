"use client";

import { useTranslations } from "next-intl";
import { RotateCcw, Maximize2 } from "lucide-react";

interface Props {
  onRearrange: () => void;
  onFit: () => void;
}

export function CanvasControls({ onRearrange, onFit }: Props) {
  const t = useTranslations("console-notebooks");
  const btnStyle = {
    display: "inline-flex", alignItems: "center", gap: 4,
    padding: "4px 8px", fontSize: 12, fontWeight: 500,
    background: "rgba(255,255,255,0.88)",
    backdropFilter: "blur(12px)",
    border: "1px solid rgba(15,42,45,0.1)", borderRadius: 8,
    color: "var(--text-primary, #0f172a)", cursor: "pointer",
  } as const;

  return (
    <div
      className="mg-canvas-controls"
      style={{
        position: "absolute", top: 12, right: 12,
        display: "flex", gap: 6, zIndex: 2,
      }}
    >
      <button data-testid="mg-btn-rearrange" type="button" onClick={onRearrange} style={btnStyle}>
        <RotateCcw size={12} /> {t("memoryGraph.rearrange")}
      </button>
      <button data-testid="mg-btn-fit" type="button" onClick={onFit} style={btnStyle}>
        <Maximize2 size={12} /> {t("memoryGraph.fit")}
      </button>
    </div>
  );
}
