"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Plus, BookOpen, Trash2, Clock } from "lucide-react";
import { apiGet, apiPost, apiDelete } from "@/lib/api";

interface NotebookItem {
  id: string;
  title: string;
  description: string;
  notebook_type: string;
  updated_at: string;
  created_at: string;
}

export default function NotebooksPage() {
  const t = useTranslations("console-notebooks");
  const router = useRouter();
  const [notebooks, setNotebooks] = useState<NotebookItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const data = await apiGet<{ items: NotebookItem[]; total: number }>("/api/v1/notebooks");
        if (!cancelled) {
          setNotebooks(data.items || []);
        }
      } catch {
        if (!cancelled) {
          setNotebooks([]);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const handleCreate = useCallback(async () => {
    if (creating) return;
    setCreating(true);
    try {
      const nb = await apiPost<NotebookItem>("/api/v1/notebooks", {
        title: "",
        notebook_type: "personal",
      });
      router.push(`/app/notebooks/${nb.id}`);
    } catch {
      // ignore
    }
    setCreating(false);
  }, [creating, router]);

  const handleDelete = useCallback(async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await apiDelete(`/api/v1/notebooks/${id}`);
      setNotebooks((prev) => prev.filter((n) => n.id !== id));
    } catch {
      // ignore
    }
  }, []);

  const formatDate = (dateStr: string) =>
    new Date(dateStr).toLocaleDateString(undefined, { month: "short", day: "numeric" });

  const getTypeLabel = (type: string) => {
    const map: Record<string, string> = {
      personal: t("notebooks.personal"),
      work: t("notebooks.work"),
      study: t("notebooks.study"),
      scratch: t("notebooks.scratch"),
    };
    return map[type] || type;
  };

  return (
    <div className="console-page-shell" style={{ padding: "24px 32px" }}>
      {/* Header */}
      <div style={{ width: "100%" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
          <div>
            <h1 style={{ fontSize: "1.625rem", fontWeight: 700, color: "var(--console-text-primary, #1a1a2e)", fontFamily: "var(--font-sora, var(--font-sans))", marginBottom: 4 }}>
              {t("notebooks.title")}
            </h1>
            <p style={{ fontSize: "0.875rem", color: "var(--console-text-muted, #6b7280)", margin: 0 }}>
              {notebooks.length > 0 ? `${notebooks.length} ${t("notebooks.title").toLowerCase()}` : ""}
            </p>
          </div>
          <button
            onClick={handleCreate}
            disabled={creating}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              padding: "10px 20px",
              background: "var(--console-accent-gradient, linear-gradient(135deg, #2563EB, #3B82F6))",
              color: "white",
              border: "none",
              borderRadius: 12,
              fontSize: "0.875rem",
              fontWeight: 600,
              cursor: creating ? "not-allowed" : "pointer",
              opacity: creating ? 0.6 : 1,
              boxShadow: "0 2px 8px rgba(37, 99, 235, 0.25)",
              transition: "all 200ms ease",
            }}
          >
            <Plus size={16} />
            {t("notebooks.create")}
          </button>
        </div>

        {/* Loading */}
        {loading && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 16 }}>
            {[1, 2, 3].map((i) => (
              <div key={i} style={{
                height: 180,
                borderRadius: 16,
                background: "rgba(255, 255, 255, 0.5)",
                border: "1px solid rgba(15, 23, 42, 0.06)",
                animation: "pulse 1.5s ease-in-out infinite",
              }} />
            ))}
          </div>
        )}

        {/* Empty state */}
        {!loading && notebooks.length === 0 && (
          <div style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            minHeight: 400,
            textAlign: "center",
          }}>
            <div style={{
              width: 80,
              height: 80,
              borderRadius: 20,
              background: "rgba(37, 99, 235, 0.06)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              marginBottom: 20,
            }}>
              <BookOpen size={36} strokeWidth={1.5} color="#2563EB" />
            </div>
            <h3 style={{ fontSize: "1.125rem", fontWeight: 600, color: "var(--console-text-primary)", marginBottom: 8 }}>
              {t("notebooks.title")}
            </h3>
            <p style={{ fontSize: "0.875rem", color: "var(--console-text-muted)", maxWidth: 320, marginBottom: 24, lineHeight: 1.6 }}>
              {t("notebooks.empty")}
            </p>
            <button
              onClick={handleCreate}
              disabled={creating}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                padding: "10px 20px",
                background: "var(--console-accent-gradient, linear-gradient(135deg, #2563EB, #3B82F6))",
                color: "white",
                border: "none",
                borderRadius: 12,
                fontSize: "0.875rem",
                fontWeight: 600,
                cursor: "pointer",
                boxShadow: "0 2px 8px rgba(37, 99, 235, 0.25)",
              }}
            >
              <Plus size={16} />
              {t("notebooks.create")}
            </button>
          </div>
        )}

        {/* Notebook grid */}
        {!loading && notebooks.length > 0 && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 16 }}>
            {notebooks.map((nb) => (
              <div
                key={nb.id}
                className="notebook-card"
                onClick={() => router.push(`/app/notebooks/${nb.id}`)}
                style={{ cursor: "pointer" }}
              >
                <div className="notebook-card-header">
                  <div style={{
                    width: 40,
                    height: 40,
                    borderRadius: 10,
                    background: "rgba(37, 99, 235, 0.08)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}>
                    <BookOpen size={20} color="var(--console-accent, #2563EB)" />
                  </div>
                  <button
                    type="button"
                    className="notebook-card-menu"
                    onClick={(e) => handleDelete(nb.id, e)}
                    title="Delete"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
                <h3 className="notebook-card-title">
                  {nb.title || t("notebooks.untitled")}
                </h3>
                <p className="notebook-card-desc">
                  {nb.description || getTypeLabel(nb.notebook_type)}
                </p>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: "auto" }}>
                  <span style={{
                    fontSize: "0.6875rem",
                    padding: "2px 8px",
                    borderRadius: 6,
                    background: "rgba(37, 99, 235, 0.06)",
                    color: "var(--console-accent, #2563EB)",
                    fontWeight: 500,
                  }}>
                    {getTypeLabel(nb.notebook_type)}
                  </span>
                  <span className="notebook-card-date" style={{ display: "flex", alignItems: "center", gap: 4 }}>
                    <Clock size={12} />
                    {formatDate(nb.updated_at)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
