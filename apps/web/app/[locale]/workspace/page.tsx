"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { BookOpen, FileText, Clock, Plus, Sparkles } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";

interface NotebookItem {
  id: string;
  title: string;
  description: string;
  notebook_type: string;
  updated_at: string;
}

interface PageItem {
  id: string;
  notebook_id: string;
  title: string;
  page_type: string;
  updated_at: string;
}

export default function DashboardPage() {
  const t = useTranslations("console");
  const tn = useTranslations("console-notebooks");
  const router = useRouter();
  const [notebooks, setNotebooks] = useState<NotebookItem[]>([]);
  const [recentPages, setRecentPages] = useState<PageItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      apiGet<{ items: NotebookItem[] }>("/api/v1/notebooks").catch(() => ({ items: [] })),
      apiGet<{ items: PageItem[] }>("/api/v1/pages/search?q=").catch(() => ({ items: [] })),
    ]).then(([nbData, pgData]) => {
      setNotebooks(nbData.items || []);
      setRecentPages((pgData.items || []).slice(0, 3));
      setLoading(false);
    });
  }, []);

  const handleCreateNotebook = useCallback(async () => {
    try {
      const nb = await apiPost<NotebookItem>("/api/v1/notebooks", { title: "", notebook_type: "personal" });
      router.push(`/app/notebooks/${nb.id}`);
    } catch { /* ignore */ }
  }, [router]);

  const formatDate = (d: string) => {
    const diff = Date.now() - new Date(d).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return t("time.justNow");
    if (mins < 60) return t("time.minutesAgo", { n: mins });
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return t("time.hoursAgo", { n: hrs });
    const days = Math.floor(hrs / 24);
    return t("time.daysAgo", { n: days });
  };

  if (loading) {
    return (
      <div className="console-page-shell" style={{ padding: "32px 40px" }}>
        <div style={{ width: "100%" }}>
          <div style={{ height: 40, width: 300, borderRadius: 8, background: "rgba(255,255,255,0.5)", marginBottom: 32 }} />
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
            {[1, 2, 3].map(i => <div key={i} style={{ height: 120, borderRadius: 16, background: "rgba(255,255,255,0.4)" }} />)}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="console-page-shell" style={{ padding: "24px 32px", display: "block" }}>
        {/* Welcome */}
        <div style={{ marginBottom: 24 }}>
          <h1 style={{ fontSize: "1.5rem", fontWeight: 700, color: "var(--console-text-primary)", fontFamily: "var(--font-sora, var(--font-sans))", marginBottom: 2 }}>
            {t("dashboard.welcome")}
          </h1>
          <p style={{ fontSize: "0.8125rem", color: "var(--console-text-muted)", margin: 0 }}>
            {notebooks.length} {t("nav.notebooks").toLowerCase()} · {recentPages.length} {t("nav.pages").toLowerCase()}
          </p>
        </div>

        {/* Continue Writing */}
        {recentPages.length > 0 && (
          <section style={{ marginBottom: 20 }}>
            <h2 style={{ fontSize: "1rem", fontWeight: 600, color: "var(--console-text-primary)", marginBottom: 16, display: "flex", alignItems: "center", gap: 8 }}>
              <Sparkles size={18} color="var(--console-accent, #2563EB)" />
              {t("dashboard.continueWriting")}
            </h2>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 12 }}>
              {recentPages.map(page => (
                <div
                  key={page.id}
                  onClick={() => router.push(`/app/notebooks/${page.notebook_id}/pages/${page.id}`)}
                  style={{
                    padding: 16,
                    background: "rgba(255,255,255,0.72)",
                    backdropFilter: "blur(18px)",
                    border: "1px solid rgba(15,23,42,0.08)",
                    borderRadius: 12,
                    cursor: "pointer",
                    transition: "all 200ms ease",
                  }}
                  className="notebook-card"
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                    <FileText size={16} color="var(--console-accent, #2563EB)" />
                    <span style={{ fontSize: "0.9375rem", fontWeight: 600, color: "var(--console-text-primary)" }}>
                      {page.title || tn("common.untitled")}
                    </span>
                  </div>
                  <span style={{ fontSize: "0.75rem", color: "var(--console-text-muted)", display: "flex", alignItems: "center", gap: 4 }}>
                    <Clock size={12} /> {formatDate(page.updated_at)}
                  </span>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* My Notebooks */}
        <section style={{ marginBottom: 20 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
            <h2 style={{ fontSize: "1rem", fontWeight: 600, color: "var(--console-text-primary)", display: "flex", alignItems: "center", gap: 8 }}>
              <BookOpen size={18} color="var(--console-accent, #2563EB)" />
              {t("dashboard.myNotebooks")}
            </h2>
            <button
              onClick={handleCreateNotebook}
              style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "6px 14px", background: "var(--console-accent-gradient, linear-gradient(135deg, #2563EB, #3B82F6))",
                color: "white", border: "none", borderRadius: 8,
                fontSize: "0.8125rem", fontWeight: 600, cursor: "pointer",
              }}
            >
              <Plus size={14} /> {tn("notebooks.create")}
            </button>
          </div>
          {notebooks.length === 0 ? (
            <div style={{ textAlign: "center", padding: 40, color: "var(--console-text-muted)", fontSize: "0.875rem" }}>
              {t("dashboard.noNotebooks")}
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 12 }}>
              {notebooks.map(nb => (
                <div
                  key={nb.id}
                  onClick={() => router.push(`/app/notebooks/${nb.id}`)}
                  className="notebook-card"
                  style={{
                    padding: 16,
                    background: "rgba(255,255,255,0.72)",
                    backdropFilter: "blur(18px)",
                    border: "1px solid rgba(15,23,42,0.08)",
                    borderRadius: 12,
                    cursor: "pointer",
                    transition: "all 200ms ease",
                  }}
                >
                  <div style={{ marginBottom: 10 }}>
                    <div style={{ width: 36, height: 36, borderRadius: 9, background: "rgba(37,99,235,0.08)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                      <BookOpen size={18} color="var(--console-accent, #2563EB)" />
                    </div>
                  </div>
                  <h3 style={{ fontSize: "0.9375rem", fontWeight: 600, color: "var(--console-text-primary)", margin: "0 0 6px 0" }}>{nb.title || tn("common.untitled")}</h3>
                  <span style={{ fontSize: "0.75rem", color: "var(--console-text-muted)", display: "flex", alignItems: "center", gap: 4 }}>
                    <Clock size={12} /> {formatDate(nb.updated_at)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Recent Chats */}
        <section>
          <h2 style={{ fontSize: "1rem", fontWeight: 600, color: "var(--console-text-primary)", marginBottom: 16, display: "flex", alignItems: "center", gap: 8 }}>
            {t("dashboard.recentChats")}
          </h2>
          <div style={{ textAlign: "center", padding: 40, color: "var(--console-text-muted)", fontSize: "0.875rem" }}>
            {t("dashboard.noChats")}
          </div>
        </section>
    </div>
  );
}
