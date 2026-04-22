"use client";

import { FileText, Brain } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRelatedPages } from "@/hooks/useRelatedPages";

interface RelatedTabProps {
  pageId: string;
}

export default function RelatedTab({ pageId }: RelatedTabProps) {
  const t = useTranslations("console-notebooks");
  const data = useRelatedPages(pageId);

  const hasAny = data.pages.length > 0 || data.memory.length > 0;
  if (!hasAny) {
    return (
      <div style={{ padding: 24, fontSize: "0.8125rem", color: "var(--console-text-muted)", textAlign: "center" }}>
        {t("related.empty")}
      </div>
    );
  }

  return (
    <div style={{ padding: "12px 16px", display: "flex", flexDirection: "column", gap: 12 }}>
      {data.pages.length > 0 && (
        <section>
          <div style={{ fontSize: "0.6875rem", color: "var(--console-text-muted)", marginBottom: 6 }}>
            {t("search.relatedPages")}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {data.pages.map((p) => (
              <div
                key={p.id}
                style={{
                  padding: "8px 12px",
                  borderRadius: "var(--console-radius-sm)",
                  background: "var(--console-surface)",
                  border: "1px solid var(--console-border-subtle)",
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                <FileText size={14} style={{ color: "var(--console-text-muted)" }} />
                <span style={{ fontSize: "0.8125rem", color: "var(--console-text-primary)", flex: 1 }}>
                  {p.title || t("common.untitled")}
                </span>
                <span style={{ fontSize: "0.6875rem", color: "var(--console-text-muted)" }}>
                  {p.reason}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {data.memory.length > 0 && (
        <section>
          <div style={{ fontSize: "0.6875rem", color: "var(--console-text-muted)", marginBottom: 6 }}>
            {t("search.relatedMemory")}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {data.memory.map((m) => (
              <div
                key={m.id}
                style={{
                  padding: "8px 12px",
                  borderRadius: "var(--console-radius-sm)",
                  background: "var(--console-surface)",
                  border: "1px solid var(--console-border-subtle)",
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 8,
                }}
              >
                <Brain size={14} style={{ color: "var(--console-text-muted)", marginTop: 2 }} />
                <span style={{ fontSize: "0.8125rem", color: "var(--console-text-primary)", lineHeight: 1.4 }}>
                  {m.content.slice(0, 160)}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
