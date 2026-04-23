"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Settings, Save } from "lucide-react";
import {
  notebookSDK,
  type NotebookInfo,
  type NotebookType,
} from "@/lib/notebook-sdk";
import { toast } from "@/hooks/use-toast";

const NOTEBOOK_TYPES: NotebookType[] = ["personal", "work", "study", "scratch"];

export default function NotebookSettingsPage() {
  const params = useParams<{ notebookId: string }>();
  const t = useTranslations("console");
  const tn = useTranslations("console-notebooks");
  const [notebook, setNotebook] = useState<NotebookInfo | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [notebookType, setNotebookType] = useState<NotebookType>("personal");
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void notebookSDK
      .get(params.notebookId)
      .then((data) => {
        setNotebook(data);
        setTitle(data.title || "");
        setDescription(data.description || "");
        if (
          data.notebook_type &&
          (NOTEBOOK_TYPES as readonly string[]).includes(data.notebook_type)
        ) {
          setNotebookType(data.notebook_type as NotebookType);
        }
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [params.notebookId]);

  const handleSave = useCallback(async () => {
    if (saving) return;
    setSaving(true);
    try {
      const updated = await notebookSDK.patch(params.notebookId, {
        title,
        description,
        notebook_type: notebookType,
      });
      setNotebook(updated);
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : tn("pages.error.update_failed");
      toast({
        title: tn("pages.error.update_failed"),
        description: message,
      });
    }
    setSaving(false);
  }, [params.notebookId, title, description, notebookType, saving, tn]);

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

        {/* Notebook type */}
        <fieldset
          style={{
            marginBottom: 24,
            padding: 0,
            border: "none",
            display: "grid",
            gap: 8,
          }}
          data-testid="notebook-settings-type"
        >
          <legend style={{ fontSize: "0.8125rem", fontWeight: 600, color: "var(--console-text-secondary)", padding: 0 }}>
            {tn("pages.create_dialog.notebook_type.heading")}
          </legend>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8 }}>
            {NOTEBOOK_TYPES.map((kind) => {
              const selected = notebookType === kind;
              return (
                <label
                  key={kind}
                  data-testid={`notebook-settings-type-${kind}`}
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 8,
                    padding: "10px 12px",
                    border: `1px solid ${selected ? "#2563eb" : "rgba(15,23,42,0.12)"}`,
                    borderRadius: 10,
                    background: selected ? "rgba(37,99,235,0.08)" : "rgba(255,255,255,0.6)",
                    cursor: "pointer",
                  }}
                >
                  <input
                    type="radio"
                    name="notebook-settings-type"
                    value={kind}
                    checked={selected}
                    onChange={() => setNotebookType(kind)}
                    style={{ marginTop: 2 }}
                  />
                  <div>
                    <div style={{ fontSize: "0.8125rem", fontWeight: 600 }}>
                      {tn(`pages.create_dialog.notebook_type.${kind}`)}
                    </div>
                    <div style={{ marginTop: 2, fontSize: "0.75rem", color: "var(--console-text-muted, #64748b)" }}>
                      {tn(`pages.create_dialog.notebook_type.${kind}_hint`)}
                    </div>
                  </div>
                </label>
              );
            })}
          </div>
        </fieldset>

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
