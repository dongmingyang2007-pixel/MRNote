"use client";

import { useTranslations } from "next-intl";
import { useProjectContext } from "@/lib/ProjectContext";
import { buildProjectDisplayMap } from "@/lib/project-display";

export function GlassStatusBar() {
  const { projectId, projects } = useProjectContext();
  const currentProject = projects.find((p) => p.id === projectId);
  const projectLabels = buildProjectDisplayMap(projects);
  const t = useTranslations("console");

  return (
    <div
      className="glass-statusbar statusbar"
      role="status"
      aria-live="polite"
      style={{
        position: "fixed",
        bottom: 0,
        left: 56,
        right: 0,
        height: 28,
        background: "rgba(250, 253, 252, 0.78)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        borderTop: "1px solid var(--console-border-subtle)",
        zIndex: 45,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 12px",
        fontSize: 11,
        color: "var(--console-text-secondary)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span
          title={t("statusbar.apiConnected")}
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: "#22c55e",
            display: "inline-block",
            flexShrink: 0,
          }}
        />
        <span>
          {currentProject
            ? (projectLabels.get(currentProject.id) || currentProject.name)
            : t("statusbar.noProject")}
        </span>
      </div>
      <div>
        <span>v0.1</span>
      </div>

      {/* Responsive: hide sidebar offset on mobile */}
      <style>{`
        @media (max-width: 768px) {
          .glass-statusbar {
            left: 0 !important;
            display: none !important;
          }
        }
      `}</style>
    </div>
  );
}
