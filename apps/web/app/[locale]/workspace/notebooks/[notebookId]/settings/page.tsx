"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Settings, Save } from "lucide-react";
import { apiGet, apiPatch } from "@/lib/api";

interface NotebookInfo {
  id: string;
  title: string;
  description: string;
  notebook_type: string;
  project_id: string | null;
}

export default function NotebookSettingsPage() {
  const params = useParams<{ notebookId: string }>();
  const t = useTranslations("console");
  const tn = useTranslations("console-notebooks");
  const [notebook, setNotebook] = useState<NotebookInfo | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void apiGet<NotebookInfo>(`/api/v1/notebooks/${params.notebookId}`)
      .then((data) => {
        setNotebook(data);
        setTitle(data.title || "");
        setDescription(data.description || "");
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [params.notebookId]);

  const handleSave = useCallback(async () => {
    if (saving) return;
    setSaving(true);
    try {
      const updated = await apiPatch<NotebookInfo>(`/api/v1/notebooks/${params.notebookId}`, {
        title,
        description,
      });
      setNotebook(updated);
    } catch {
      // ignore
    }
    setSaving(false);
  }, [params.notebookId, title, description, saving]);

  if (loading) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--console-text-muted)" }}>
        {tn("common.loading")}
      </div>
    );
  }

  return (
    <div style={{ height: "100%", overflow: "auto", padding: "32px 40px" }}>
      <div style={{ maxWidth: 560, margin: "0 auto" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 32 }}>
          <Settings size={24} color="var(--console-accent, #2563EB)" />
          <h2 style={{ fontSize: "1.375rem", fontWeight: 700, color: "var(--console-text-primary)", fontFamily: "var(--font-sora, var(--font-sans))" }}>
            {t("nav.notebookSettings")}
          </h2>
        </div>

        {/* Title */}
        <div style={{ marginBottom: 20 }}>
          <label style={{ display: "block", fontSize: "0.8125rem", fontWeight: 600, color: "var(--console-text-secondary)", marginBottom: 6 }}>
            {tn("common.title")}
          </label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            style={{
              width: "100%",
              padding: "10px 14px",
              fontSize: "0.9375rem",
              border: "1px solid var(--console-border, rgba(255,255,255,0.7))",
              borderRadius: 10,
              background: "rgba(255,255,255,0.6)",
              color: "var(--console-text-primary)",
              outline: "none",
            }}
          />
        </div>

        {/* Description */}
        <div style={{ marginBottom: 24 }}>
          <label style={{ display: "block", fontSize: "0.8125rem", fontWeight: 600, color: "var(--console-text-secondary)", marginBottom: 6 }}>
            {tn("common.description")}
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            style={{
              width: "100%",
              padding: "10px 14px",
              fontSize: "0.875rem",
              border: "1px solid var(--console-border, rgba(255,255,255,0.7))",
              borderRadius: 10,
              background: "rgba(255,255,255,0.6)",
              color: "var(--console-text-primary)",
              outline: "none",
              resize: "vertical",
            }}
          />
        </div>

        {/* Info */}
        {notebook?.project_id && (
          <div style={{ marginBottom: 24, padding: "12px 16px", background: "rgba(255,255,255,0.5)", borderRadius: 10, fontSize: "0.8125rem", color: "var(--console-text-muted)" }}>
            {tn("settings.projectId")}: {notebook.project_id}
          </div>
        )}

        {/* Save button */}
        <button
          onClick={handleSave}
          disabled={saving}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            padding: "10px 20px",
            background: "var(--console-accent-gradient, linear-gradient(135deg, #2563EB, #3B82F6))",
            color: "white",
            border: "none",
            borderRadius: 10,
            fontSize: "0.875rem",
            fontWeight: 600,
            cursor: saving ? "not-allowed" : "pointer",
            opacity: saving ? 0.6 : 1,
          }}
        >
          <Save size={16} />
          {saving ? tn("common.saving") : tn("common.save")}
        </button>
      </div>
    </div>
  );
}
