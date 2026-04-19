"use client";

import { useTranslations } from "next-intl";
import { Brain } from "lucide-react";

export function HeaderBar() {
  const t = useTranslations("console-notebooks");
  return (
    <div
      className="mg-header"
      style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "10px 14px",
        borderBottom: "1px solid var(--border, rgba(15,42,45,0.08))",
        fontSize: 14,
      }}
    >
      <Brain size={16} strokeWidth={1.8} style={{ color: "var(--accent, #0d9488)" }} />
      <span style={{ fontWeight: 700, color: "var(--text-primary, #0f172a)" }}>
        {t("memoryGraph.title")}
      </span>
      <span style={{ color: "var(--text-secondary, #64748b)", fontSize: 13 }}>
        {t("memoryGraph.header.brand")}
      </span>
    </div>
  );
}
