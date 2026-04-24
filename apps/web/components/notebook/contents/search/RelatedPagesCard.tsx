"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRelatedPages } from "@/hooks/useRelatedPages";
import { useWindowManager } from "@/components/notebook/WindowManager";

interface Props {
  pageId: string;
}

export default function RelatedPagesCard({ pageId }: Props) {
  const t = useTranslations("console-notebooks");
  const { openWindow } = useWindowManager();
  const data = useRelatedPages(pageId);
  const [open, setOpen] = useState(false);

  if (data.pages.length === 0 && data.memory.length === 0) return null;

  return (
    <aside
      className="related-pages-card"
      data-testid="related-pages-card"
      style={{
        borderTop: "1px solid #e5e7eb",
        padding: "10px 16px",
        fontSize: 12,
      }}
    >
      <button
        type="button"
        data-testid="related-pages-card-toggle"
        onClick={() => setOpen((v) => !v)}
        style={{
          display: "flex", alignItems: "center", gap: 6,
          background: "none", border: "none", cursor: "pointer",
          padding: 0, fontWeight: 600, color: "#374151",
        }}
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <Sparkles size={13} />
        {t("search.related", { count: data.pages.length + data.memory.length })}
      </button>

      {open && (
        <div style={{ marginTop: 8 }}>
          {data.pages.length > 0 && (
            <div>
              <div style={{ fontSize: 10, color: "#9ca3af", marginBottom: 4 }}>
                {t("search.relatedPages")}
              </div>
              <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                {data.pages.map((p) => (
                  <li key={p.id} style={{ padding: "4px 0" }}>
                    <button
                      type="button"
                      data-testid="related-pages-link"
                      onClick={() =>
                        openWindow({
                          type: "note", title: p.title || t("search.untitled"),
                          meta: { pageId: p.id, notebookId: p.notebook_id },
                        })
                      }
                      style={{
                        background: "none", border: "none",
                        cursor: "pointer", color: "var(--console-accent, #0D9488)",
                        fontSize: 12, padding: 0, textAlign: "left",
                      }}
                    >
                      {p.title || t("search.untitled")}
                    </button>
                    <span style={{ color: "#9ca3af", fontSize: 10, marginLeft: 6 }}>
                      · {p.reason}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {data.memory.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 10, color: "#9ca3af", marginBottom: 4 }}>
                {t("search.relatedMemory")}
              </div>
              <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                {data.memory.map((m) => (
                  <li key={m.id} style={{ padding: "2px 0", color: "#374151" }}>
                    {m.content.slice(0, 100)}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </aside>
  );
}
