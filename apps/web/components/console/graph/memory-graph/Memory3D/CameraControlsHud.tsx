"use client";

import { useTranslations } from "next-intl";
import { Plus, Minus, Maximize2, RotateCw } from "lucide-react";

interface Props {
  zoomPct: number;
  autoRotating: boolean;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFit: () => void;
  onToggleAutoRotate: () => void;
}

export function CameraControlsHud({ zoomPct, autoRotating, onZoomIn, onZoomOut, onFit, onToggleAutoRotate }: Props) {
  const t = useTranslations("console-notebooks");
  const btnStyle = { padding: 4, background: "transparent", border: "none", cursor: "pointer", color: "var(--text-primary)" } as const;

  return (
    <div
      style={{
        position: "absolute", bottom: 12, left: 12,
        background: "rgba(255,255,255,0.88)", backdropFilter: "blur(12px)",
        padding: 6, borderRadius: 10,
        border: "1px solid rgba(15,42,45,0.1)",
        display: "flex", alignItems: "center", gap: 4, zIndex: 2,
      }}
    >
      <button data-testid="mg3d-zoom-out" type="button" onClick={onZoomOut} aria-label={t("memoryGraph.camera.zoomOut")} style={btnStyle}>
        <Minus size={14} />
      </button>
      <span style={{ minWidth: 42, textAlign: "center", fontSize: 12 }}>{Math.round(zoomPct)}%</span>
      <button data-testid="mg3d-zoom-in" type="button" onClick={onZoomIn} aria-label={t("memoryGraph.camera.zoomIn")} style={btnStyle}>
        <Plus size={14} />
      </button>
      <button data-testid="mg3d-fit" type="button" onClick={onFit} aria-label={t("memoryGraph.camera.fit")} style={btnStyle}>
        <Maximize2 size={14} />
      </button>
      <button
        data-testid="mg3d-auto-rotate"
        type="button" onClick={onToggleAutoRotate}
        aria-label={t("memoryGraph.camera.autoRotate")}
        aria-pressed={autoRotating}
        style={{ ...btnStyle, color: autoRotating ? "var(--accent, #0d9488)" : btnStyle.color }}
      >
        <RotateCw size={14} />
      </button>
    </div>
  );
}
