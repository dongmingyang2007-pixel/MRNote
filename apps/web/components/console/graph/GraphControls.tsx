"use client";

import { useTranslations } from "next-intl";

interface GraphControlsProps {
  nodeCount: number;
  fileCount: number;
  branchCount: number;
  relatedCount: number;
  temporaryCount: number;
  renderMode: "workbench" | "orbit";
  onAdd: () => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFitView: () => void;
}

export default function GraphControls({
  nodeCount,
  fileCount,
  branchCount,
  relatedCount,
  temporaryCount,
  renderMode,
  onAdd,
  searchQuery,
  onSearchChange,
  onZoomIn,
  onZoomOut,
  onFitView,
}: GraphControlsProps) {
  const t = useTranslations("console-assistants");
  const modeTitle = renderMode === "orbit" ? t("graph.modeOrbit") : t("graph.modeWorkbench");
  const modeCaption =
    renderMode === "orbit" ? t("graph.modeOrbitCaption") : t("graph.modeWorkbenchCaption");
  const modeHint = renderMode === "orbit" ? t("graph.orbitInteractionHint") : null;

  return (
    <div className={`graph-controls graph-controls--${renderMode}`}>
      <div className="graph-controls-left">
        <div className="graph-controls-mode">
          <span className={`graph-controls-mode-badge is-${renderMode}`}>{modeTitle}</span>
          <div className="graph-controls-mode-copy">
            <strong>{t("graph.stats", { count: nodeCount })}</strong>
            <span>{modeCaption}</span>
            {modeHint ? <span className="graph-controls-mode-hint">{modeHint}</span> : null}
          </div>
        </div>
        <input
          type="text"
          className="graph-controls-search"
          placeholder={t("graph.search")}
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
        />
      </div>
      <div className="graph-controls-center">
        <span className="graph-controls-legend is-structure">{t("graph.legendStructure")}</span>
        <span className="graph-controls-legend is-related">{t("graph.legendRelated")}</span>
        <span className="graph-controls-legend is-summary">{t("graph.legendSummary")}</span>
        <span className="graph-controls-legend is-temporary">{t("graph.legendTemporary")}</span>
      </div>
      <div className="graph-controls-right">
        <span className="graph-controls-stats">{t("graph.branchCount", { count: branchCount })}</span>
        <span className="graph-controls-stats">{t("graph.relatedCount", { count: relatedCount })}</span>
        {temporaryCount > 0 ? (
          <span className="graph-controls-stats">{t("graph.temporaryCount", { count: temporaryCount })}</span>
        ) : null}
        {fileCount > 0 ? (
          <span className="graph-controls-stats">{t("graph.statsFiles", { count: fileCount })}</span>
        ) : null}
        <button className="graph-controls-btn is-add" onClick={onAdd}>
          + {t("graph.addMemory")}
        </button>
        <button className="graph-controls-btn is-zoom" onClick={onZoomIn} title={t("graph.zoomIn")} aria-label={t("graph.zoomIn")}>
          +
        </button>
        <button className="graph-controls-btn is-zoom" onClick={onZoomOut} title={t("graph.zoomOut")} aria-label={t("graph.zoomOut")}>
          &minus;
        </button>
        <button className="graph-controls-btn is-zoom" onClick={onFitView} title={t("graph.fitView")} aria-label={t("graph.fitView")}>
          ⊞
        </button>
      </div>
    </div>
  );
}
