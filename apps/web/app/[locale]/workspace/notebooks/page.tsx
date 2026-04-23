"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import {
  BookOpen,
  Brain,
  Clock3,
  Plus,
  Sparkles,
  Trash2,
} from "lucide-react";
import { apiGet } from "@/lib/api";
import { notebookSDK, type CreateNotebookInput } from "@/lib/notebook-sdk";
import { NOTEBOOKS_CHANGED_EVENT, dispatchNotebooksChanged } from "@/lib/notebook-events";
import CreateNotebookDialog from "@/components/notebook/CreateNotebookDialog";
import { toast } from "@/hooks/use-toast";

interface NotebookCard {
  id: string;
  title: string;
  description: string;
  notebook_type: string;
  updated_at: string;
  page_count: number;
  study_asset_count: number;
  ai_action_count: number;
}

interface HomePageItem {
  id: string;
  notebook_id: string;
  notebook_title: string;
  title: string;
  updated_at: string;
  last_edited_at: string | null;
  plain_text_preview: string;
}

interface HomeStudyAsset {
  id: string;
  notebook_id: string;
  notebook_title: string;
  title: string;
  status: string;
  asset_type: string;
  total_chunks: number;
  created_at: string;
}

interface HomeAIAction {
  id: string;
  notebook_id: string | null;
  page_id: string | null;
  notebook_title: string | null;
  page_title: string | null;
  action_type: string;
  output_summary: string;
  created_at: string;
}

interface FocusItem {
  notebook_id: string;
  notebook_title: string;
  page_count: number;
  study_asset_count: number;
  ai_action_count: number;
}

interface HomeSummary {
  notebooks: NotebookCard[];
  recent_pages: HomePageItem[];
  continue_writing: HomePageItem[];
  recent_study_assets: HomeStudyAsset[];
  ai_today: {
    actions_today: number;
    top_action_types: Array<{ action_type: string; count: number }>;
    recent_actions: HomeAIAction[];
  };
  work_themes: FocusItem[];
  long_term_focus: FocusItem[];
  recommended_pages: HomePageItem[];
}

const surfaceStyle: React.CSSProperties = {
  border: "1px solid var(--console-border-subtle, rgba(15, 23, 42, 0.08))",
  borderRadius: 20,
  background: "rgba(255,255,255,0.72)",
  backdropFilter: "blur(20px)",
  WebkitBackdropFilter: "blur(20px)",
  boxShadow: "0 20px 60px rgba(15, 23, 42, 0.08)",
};

function relDate(value: string): string {
  const date = new Date(value);
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function SectionHeader({
  title,
  body,
  action,
}: {
  title: string;
  body?: string;
  action?: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-end",
        justifyContent: "space-between",
        gap: 12,
        marginBottom: 16,
      }}
    >
      <div>
        <h2
          style={{
            margin: 0,
            fontSize: "1rem",
            fontWeight: 700,
            color: "var(--console-text-primary, #0f172a)",
          }}
        >
          {title}
        </h2>
        {body ? (
          <p
            style={{
              margin: "6px 0 0",
              fontSize: "0.8125rem",
              color: "var(--console-text-muted, #64748b)",
            }}
          >
            {body}
          </p>
        ) : null}
      </div>
      {action}
    </div>
  );
}

export default function NotebooksPage() {
  const t = useTranslations("console-notebooks");
  const router = useRouter();
  const [home, setHome] = useState<HomeSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);

  const loadHome = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet<HomeSummary>("/api/v1/notebooks/home");
      setHome(data);
    } catch {
      setHome({
        notebooks: [],
        recent_pages: [],
        continue_writing: [],
        recent_study_assets: [],
        ai_today: { actions_today: 0, top_action_types: [], recent_actions: [] },
        work_themes: [],
        long_term_focus: [],
        recommended_pages: [],
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadHome();
  }, [loadHome]);

  useEffect(() => {
    const refetch = () => {
      void loadHome();
    };
    window.addEventListener(NOTEBOOKS_CHANGED_EVENT, refetch);
    return () => window.removeEventListener(NOTEBOOKS_CHANGED_EVENT, refetch);
  }, [loadHome]);

  const openCreateDialog = useCallback(() => {
    setCreateOpen(true);
  }, []);

  const handleCreateSubmit = useCallback(
    async (input: CreateNotebookInput) => {
      if (creating) return;
      setCreating(true);
      try {
        const notebook = await notebookSDK.create(input);
        dispatchNotebooksChanged();
        setCreateOpen(false);
        router.push(`/app/notebooks/${notebook.id}`);
      } catch (error) {
        // Bubble a toast so the user sees something failed. The dialog itself
        // also renders an inline error based on the thrown message, so 402
        // plan-limit errors still surface via UpgradeModal (from api.ts) while
        // other failures are explicit here.
        const message =
          error instanceof Error ? error.message : t("pages.error.create_failed");
        toast({
          title: t("pages.error.create_failed"),
          description: message,
        });
        throw error;
      } finally {
        setCreating(false);
      }
    },
    [creating, router, t],
  );

  const handleDelete = useCallback(
    async (id: string, event: React.MouseEvent) => {
      event.stopPropagation();
      try {
        await notebookSDK.delete(id);
        dispatchNotebooksChanged();
        void loadHome();
      } catch (error) {
        const message =
          error instanceof Error ? error.message : t("pages.error.delete_failed");
        toast({
          title: t("pages.error.delete_failed"),
          description: message,
        });
      }
    },
    [loadHome, t],
  );

  const metrics = useMemo(() => {
    const notebooks = home?.notebooks ?? [];
    return {
      notebooks: notebooks.length,
      pages: notebooks.reduce((sum, notebook) => sum + notebook.page_count, 0),
      assets: notebooks.reduce((sum, notebook) => sum + notebook.study_asset_count, 0),
      ai: home?.ai_today.actions_today ?? 0,
    };
  }, [home]);

  const openPage = useCallback((page: HomePageItem) => {
    router.push(`/app/notebooks/${page.notebook_id}?openPage=${page.id}`);
  }, [router]);

  const openNotebook = useCallback((notebookId: string) => {
    router.push(`/app/notebooks/${notebookId}`);
  }, [router]);

  const openAction = useCallback((action: HomeAIAction) => {
    if (action.notebook_id && action.page_id) {
      router.push(`/app/notebooks/${action.notebook_id}?openPage=${action.page_id}`);
      return;
    }
    if (action.notebook_id) {
      router.push(`/app/notebooks/${action.notebook_id}`);
    }
  }, [router]);

  const renderFocusSummary = (item: FocusItem) =>
    t("home.focus.summary", {
      pages: item.page_count,
      assets: item.study_asset_count,
      ai: item.ai_action_count,
    });

  return (
    <div style={{ padding: "32px 32px 40px" }}>
      <div
        style={{
          ...surfaceStyle,
          padding: 28,
          marginBottom: 24,
          display: "grid",
          gridTemplateColumns: "minmax(0, 1.4fr) minmax(280px, 0.9fr)",
          gap: 24,
        }}
      >
        <div>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              padding: "6px 12px",
              borderRadius: 999,
              background: "rgba(37, 99, 235, 0.08)",
              color: "var(--console-accent, #2563eb)",
              fontSize: "0.75rem",
              fontWeight: 700,
              marginBottom: 16,
            }}
          >
            <Sparkles size={14} />
            {t("home.kicker")}
          </div>
          <h1
            style={{
              margin: 0,
              fontSize: "2rem",
              lineHeight: 1.05,
              fontWeight: 800,
              color: "var(--console-text-primary, #0f172a)",
              maxWidth: 720,
            }}
          >
            {t("home.title")}
          </h1>
          <p
            style={{
              margin: "14px 0 0",
              fontSize: "0.95rem",
              color: "var(--console-text-muted, #64748b)",
              maxWidth: 760,
              lineHeight: 1.7,
            }}
          >
            {t("home.subtitle")}
          </p>
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
            gap: 12,
            alignContent: "start",
          }}
        >
          {[
            { key: "notebooks", icon: BookOpen, value: metrics.notebooks },
            { key: "pages", icon: Clock3, value: metrics.pages },
            { key: "assets", icon: Brain, value: metrics.assets },
            { key: "ai", icon: Sparkles, value: metrics.ai },
          ].map((metric) => (
            <div
              key={metric.key}
              style={{
                borderRadius: 18,
                padding: "16px 18px",
                background: "rgba(248, 250, 252, 0.86)",
                border: "1px solid rgba(15, 23, 42, 0.08)",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  marginBottom: 12,
                  color: "var(--console-text-muted, #64748b)",
                }}
              >
                <metric.icon size={16} />
                <span style={{ fontSize: "0.75rem", fontWeight: 600 }}>
                  {t(`home.metrics.${metric.key}`)}
                </span>
              </div>
              <div style={{ fontSize: "1.5rem", fontWeight: 800, color: "var(--console-text-primary, #0f172a)" }}>
                {metric.value}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1.3fr) minmax(320px, 0.9fr)",
          gap: 24,
        }}
      >
        <div style={{ display: "grid", gap: 24 }}>
          <section style={{ ...surfaceStyle, padding: 24 }}>
            <SectionHeader
              title={t("home.sections.notebooks")}
              body={t("home.sections.notebooksBody")}
              action={(
                <button
                  type="button"
                  onClick={openCreateDialog}
                  disabled={creating}
                  data-testid="notebooks-create-button"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "10px 16px",
                    borderRadius: 999,
                    border: "none",
                    background: "linear-gradient(135deg, #2563eb, #0f4bd7)",
                    color: "#fff",
                    fontWeight: 700,
                    cursor: creating ? "default" : "pointer",
                    opacity: creating ? 0.65 : 1,
                  }}
                >
                  <Plus size={16} />
                  {t("notebooks.create")}
                </button>
              )}
            />
            {loading ? (
              <div style={{ color: "var(--console-text-muted, #64748b)", fontSize: "0.875rem" }}>
                {t("common.loading")}
              </div>
            ) : home && home.notebooks.length > 0 ? (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                  gap: 14,
                }}
              >
                {home.notebooks.map((notebook) => (
                  <div
                    key={notebook.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => openNotebook(notebook.id)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        openNotebook(notebook.id);
                      }
                    }}
                    data-testid="notebook-card"
                    style={{
                      textAlign: "left",
                      border: "1px solid rgba(15, 23, 42, 0.08)",
                      borderRadius: 20,
                      background: "rgba(248, 250, 252, 0.92)",
                      padding: 18,
                      cursor: "pointer",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
                      <div>
                        <div style={{ fontSize: "0.95rem", fontWeight: 700, color: "var(--console-text-primary, #0f172a)" }}>
                          {notebook.title || t("notebooks.untitled")}
                        </div>
                        <div style={{ marginTop: 6, fontSize: "0.75rem", color: "var(--console-text-muted, #64748b)" }}>
                          {notebook.description || t("home.notebookFallback")}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={(event) => void handleDelete(notebook.id, event)}
                        style={{
                          border: "none",
                          background: "transparent",
                          color: "var(--console-text-muted, #94a3b8)",
                          cursor: "pointer",
                        }}
                        aria-label={t("notebooks.delete")}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>

                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
                        gap: 8,
                        marginTop: 18,
                      }}
                    >
                      {[
                        { key: "pages", value: notebook.page_count },
                        { key: "assets", value: notebook.study_asset_count },
                        { key: "ai", value: notebook.ai_action_count },
                      ].map((stat) => (
                        <div
                          key={stat.key}
                          style={{
                            borderRadius: 14,
                            padding: "10px 12px",
                            background: "rgba(255,255,255,0.82)",
                            border: "1px solid rgba(15, 23, 42, 0.06)",
                          }}
                        >
                          <div style={{ fontSize: "0.6875rem", color: "var(--console-text-muted, #64748b)" }}>
                            {t(`home.metrics.${stat.key}`)}
                          </div>
                          <div style={{ marginTop: 4, fontSize: "1rem", fontWeight: 700, color: "var(--console-text-primary, #0f172a)" }}>
                            {stat.value}
                          </div>
                        </div>
                      ))}
                    </div>

                    <div style={{ marginTop: 14, fontSize: "0.75rem", color: "var(--console-text-muted, #64748b)" }}>
                      {t("home.updatedAt", { value: relDate(notebook.updated_at) })}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              /* U-01 — onboarding empty state: big CTA + 3 preset shortcuts.
                 Each preset piggy-backs on notebookSDK.create() so the
                 ProjectProvider / 402 upgrade event contract still holds. */
              <div
                data-testid="notebooks-onboarding"
                style={{
                  padding: "32px 8px 12px",
                  display: "grid",
                  gap: 18,
                }}
              >
                <div style={{ textAlign: "center" }}>
                  <div
                    style={{
                      display: "inline-flex",
                      width: 56,
                      height: 56,
                      borderRadius: 20,
                      alignItems: "center",
                      justifyContent: "center",
                      background: "linear-gradient(135deg, #2563eb, #0f4bd7)",
                      color: "#fff",
                      marginBottom: 16,
                    }}
                  >
                    <Sparkles size={26} />
                  </div>
                  <h3
                    style={{
                      margin: 0,
                      fontSize: "1.25rem",
                      fontWeight: 800,
                      color: "var(--console-text-primary, #0f172a)",
                    }}
                  >
                    {t("home.onboarding.title")}
                  </h3>
                  <p
                    style={{
                      margin: "8px auto 18px",
                      maxWidth: 480,
                      fontSize: "0.875rem",
                      color: "var(--console-text-muted, #64748b)",
                      lineHeight: 1.6,
                    }}
                  >
                    {t("home.onboarding.body")}
                  </p>
                  <button
                    type="button"
                    onClick={openCreateDialog}
                    disabled={creating}
                    data-testid="onboarding-create-button"
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 8,
                      padding: "12px 22px",
                      borderRadius: 999,
                      border: "none",
                      background: "linear-gradient(135deg, #2563eb, #0f4bd7)",
                      color: "#fff",
                      fontWeight: 700,
                      fontSize: "0.9375rem",
                      cursor: creating ? "default" : "pointer",
                      opacity: creating ? 0.65 : 1,
                      boxShadow: "0 12px 40px rgba(37, 99, 235, 0.25)",
                    }}
                  >
                    <Plus size={16} />
                    {t("home.onboarding.cta")}
                  </button>
                </div>

                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                    gap: 12,
                    marginTop: 4,
                  }}
                >
                  {([
                    {
                      id: "blank" as const,
                      type: "personal" as const,
                      icon: BookOpen,
                    },
                    {
                      id: "work" as const,
                      type: "work" as const,
                      icon: Brain,
                    },
                    {
                      id: "study" as const,
                      type: "study" as const,
                      icon: Sparkles,
                    },
                  ]).map((preset) => (
                    <button
                      key={preset.id}
                      type="button"
                      disabled={creating}
                      data-testid={`onboarding-preset-${preset.id}`}
                      onClick={() => {
                        void (async () => {
                          if (creating) return;
                          setCreating(true);
                          try {
                            const notebook = await notebookSDK.create({
                              title: t(
                                `home.onboarding.preset.${preset.id}.title` as
                                  | "home.onboarding.preset.blank.title"
                                  | "home.onboarding.preset.work.title"
                                  | "home.onboarding.preset.study.title",
                              ),
                              notebook_type: preset.type,
                            });
                            dispatchNotebooksChanged();
                            router.push(`/app/notebooks/${notebook.id}`);
                          } catch (error) {
                            const message =
                              error instanceof Error
                                ? error.message
                                : t("pages.error.create_failed");
                            toast({
                              title: t("pages.error.create_failed"),
                              description: message,
                            });
                          } finally {
                            setCreating(false);
                          }
                        })();
                      }}
                      style={{
                        textAlign: "left",
                        border: "1px solid rgba(15, 23, 42, 0.08)",
                        borderRadius: 16,
                        background: "rgba(255,255,255,0.9)",
                        padding: 16,
                        cursor: creating ? "default" : "pointer",
                        opacity: creating ? 0.65 : 1,
                        transition: "transform 120ms ease, box-shadow 120ms ease",
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div
                          style={{
                            width: 32,
                            height: 32,
                            borderRadius: 10,
                            background: "rgba(37, 99, 235, 0.1)",
                            display: "grid",
                            placeItems: "center",
                            color: "var(--console-accent, #2563eb)",
                          }}
                        >
                          <preset.icon size={16} />
                        </div>
                        <div style={{ fontWeight: 700, color: "var(--console-text-primary, #0f172a)" }}>
                          {t(
                            `home.onboarding.preset.${preset.id}.title` as
                              | "home.onboarding.preset.blank.title"
                              | "home.onboarding.preset.work.title"
                              | "home.onboarding.preset.study.title",
                          )}
                        </div>
                      </div>
                      <div
                        style={{
                          marginTop: 10,
                          fontSize: "0.75rem",
                          color: "var(--console-text-muted, #64748b)",
                          lineHeight: 1.6,
                        }}
                      >
                        {t(
                          `home.onboarding.preset.${preset.id}.body` as
                            | "home.onboarding.preset.blank.body"
                            | "home.onboarding.preset.work.body"
                            | "home.onboarding.preset.study.body",
                        )}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </section>

          <section style={{ ...surfaceStyle, padding: 24 }}>
            <SectionHeader
              title={t("home.sections.recentPages")}
              body={t("home.sections.recentPagesBody")}
            />
            <div style={{ display: "grid", gap: 10 }}>
              {(home?.recent_pages ?? []).map((page) => (
                <button
                  key={page.id}
                  type="button"
                  onClick={() => openPage(page)}
                  style={{
                    padding: "14px 16px",
                    borderRadius: 16,
                    border: "1px solid rgba(15, 23, 42, 0.08)",
                    background: "rgba(255,255,255,0.9)",
                    textAlign: "left",
                    cursor: "pointer",
                  }}
                >
                  <div style={{ fontSize: "0.875rem", fontWeight: 700, color: "var(--console-text-primary, #0f172a)" }}>
                    {page.title || t("pages.untitled")}
                  </div>
                  <div style={{ marginTop: 4, fontSize: "0.75rem", color: "var(--console-text-muted, #64748b)" }}>
                    {page.notebook_title} · {relDate(page.last_edited_at || page.updated_at)}
                  </div>
                  {page.plain_text_preview ? (
                    <div style={{ marginTop: 8, fontSize: "0.75rem", color: "var(--console-text-secondary, #475569)", lineHeight: 1.6 }}>
                      {page.plain_text_preview}
                    </div>
                  ) : null}
                </button>
              ))}
              {!loading && (home?.recent_pages.length ?? 0) === 0 ? (
                <div style={{ fontSize: "0.8125rem", color: "var(--console-text-muted, #64748b)" }}>
                  {t("home.empty.pages")}
                </div>
              ) : null}
            </div>
          </section>

          <section style={{ ...surfaceStyle, padding: 24 }}>
            <SectionHeader
              title={t("home.sections.continue")}
              body={t("home.sections.continueBody")}
            />
            <div style={{ display: "grid", gap: 10 }}>
              {(home?.continue_writing ?? []).map((page) => (
                <button
                  key={page.id}
                  type="button"
                  onClick={() => openPage(page)}
                  style={{
                    padding: "14px 16px",
                    borderRadius: 16,
                    border: "1px solid rgba(15, 23, 42, 0.08)",
                    background: "rgba(248, 250, 252, 0.86)",
                    textAlign: "left",
                    cursor: "pointer",
                  }}
                >
                  <div style={{ fontSize: "0.875rem", fontWeight: 700, color: "var(--console-text-primary, #0f172a)" }}>
                    {page.title || t("pages.untitled")}
                  </div>
                  <div style={{ marginTop: 4, fontSize: "0.75rem", color: "var(--console-text-muted, #64748b)" }}>
                    {page.notebook_title} · {relDate(page.last_edited_at || page.updated_at)}
                  </div>
                  {page.plain_text_preview ? (
                    <div style={{ marginTop: 8, fontSize: "0.75rem", color: "var(--console-text-secondary, #475569)", lineHeight: 1.6 }}>
                      {page.plain_text_preview}
                    </div>
                  ) : null}
                </button>
              ))}
              {!loading && (home?.continue_writing.length ?? 0) === 0 ? (
                <div style={{ fontSize: "0.8125rem", color: "var(--console-text-muted, #64748b)" }}>
                  {t("home.empty.pages")}
                </div>
              ) : null}
            </div>
          </section>

          <section style={{ ...surfaceStyle, padding: 24 }}>
            <SectionHeader
              title={t("home.sections.recommended")}
              body={t("home.sections.recommendedBody")}
            />
            <div style={{ display: "grid", gap: 10 }}>
              {(home?.recommended_pages ?? []).map((page) => (
                <button
                  key={page.id}
                  type="button"
                  onClick={() => openPage(page)}
                  style={{
                    padding: "12px 14px",
                    borderRadius: 14,
                    border: "1px solid rgba(15, 23, 42, 0.08)",
                    background: "rgba(255,255,255,0.9)",
                    textAlign: "left",
                    cursor: "pointer",
                  }}
                >
                  <div style={{ fontSize: "0.8125rem", fontWeight: 700, color: "var(--console-text-primary, #0f172a)" }}>
                    {page.title || t("pages.untitled")}
                  </div>
                  <div style={{ marginTop: 4, fontSize: "0.75rem", color: "var(--console-text-muted, #64748b)" }}>
                    {page.notebook_title}
                  </div>
                </button>
              ))}
            </div>
          </section>
        </div>

        <div style={{ display: "grid", gap: 24 }}>
          <section style={{ ...surfaceStyle, padding: 24 }}>
            <SectionHeader
              title={t("home.sections.study")}
              body={t("home.sections.studyBody")}
            />
            <div style={{ display: "grid", gap: 10 }}>
              {(home?.recent_study_assets ?? []).map((asset) => (
                <button
                  key={asset.id}
                  type="button"
                  onClick={() => openNotebook(asset.notebook_id)}
                  style={{
                    padding: "12px 14px",
                    borderRadius: 14,
                    border: "1px solid rgba(15, 23, 42, 0.08)",
                    background: "rgba(248, 250, 252, 0.86)",
                    textAlign: "left",
                    cursor: "pointer",
                  }}
                >
                  <div style={{ fontSize: "0.8125rem", fontWeight: 700, color: "var(--console-text-primary, #0f172a)" }}>
                    {asset.title}
                  </div>
                  <div style={{ marginTop: 4, fontSize: "0.75rem", color: "var(--console-text-muted, #64748b)" }}>
                    {asset.notebook_title} · {asset.asset_type} · {t("study.assets.chunks", { count: asset.total_chunks })}
                  </div>
                </button>
              ))}
              {!loading && (home?.recent_study_assets.length ?? 0) === 0 ? (
                <div style={{ fontSize: "0.8125rem", color: "var(--console-text-muted, #64748b)" }}>
                  {t("home.empty.study")}
                </div>
              ) : null}
            </div>
          </section>

          <section style={{ ...surfaceStyle, padding: 24 }}>
            <SectionHeader
              title={t("home.sections.aiToday")}
              body={t("home.sections.aiTodayBody", { count: home?.ai_today.actions_today ?? 0 })}
            />
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
              {(home?.ai_today.top_action_types ?? []).map((item) => (
                <span
                  key={item.action_type}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "8px 10px",
                    borderRadius: 999,
                    background: "rgba(15, 23, 42, 0.06)",
                    color: "var(--console-text-primary, #0f172a)",
                    fontSize: "0.75rem",
                    fontWeight: 600,
                  }}
                >
                  {item.action_type}
                  <span style={{ color: "var(--console-text-muted, #64748b)" }}>{item.count}</span>
                </span>
              ))}
            </div>
            <div style={{ display: "grid", gap: 10 }}>
              {(home?.ai_today.recent_actions ?? []).map((action) => (
                <button
                  key={action.id}
                  type="button"
                  onClick={() => openAction(action)}
                  style={{
                    padding: "12px 14px",
                    borderRadius: 14,
                    border: "1px solid rgba(15, 23, 42, 0.08)",
                    background: "rgba(255,255,255,0.9)",
                    textAlign: "left",
                    cursor: "pointer",
                  }}
                >
                  <div style={{ fontSize: "0.8125rem", fontWeight: 700, color: "var(--console-text-primary, #0f172a)" }}>
                    {action.page_title || action.action_type}
                  </div>
                  <div style={{ marginTop: 4, fontSize: "0.75rem", color: "var(--console-text-muted, #64748b)" }}>
                    {action.notebook_title || t("home.noNotebook")} · {relDate(action.created_at)}
                  </div>
                  <div style={{ marginTop: 8, fontSize: "0.75rem", color: "var(--console-text-secondary, #475569)", lineHeight: 1.6 }}>
                    {action.output_summary || action.action_type}
                  </div>
                </button>
              ))}
              {!loading && (home?.ai_today.recent_actions.length ?? 0) === 0 ? (
                <div style={{ fontSize: "0.8125rem", color: "var(--console-text-muted, #64748b)" }}>
                  {t("aiActions.empty")}
                </div>
              ) : null}
            </div>
          </section>

          <section style={{ ...surfaceStyle, padding: 24 }}>
            <SectionHeader
              title={t("home.sections.themes")}
              body={t("home.sections.themesBody")}
            />
            <div style={{ display: "grid", gap: 10 }}>
              {(home?.work_themes ?? []).map((item) => (
                <button
                  key={item.notebook_id}
                  type="button"
                  onClick={() => openNotebook(item.notebook_id)}
                  style={{
                    padding: "12px 14px",
                    borderRadius: 14,
                    border: "1px solid rgba(15, 23, 42, 0.08)",
                    background: "rgba(248, 250, 252, 0.86)",
                    textAlign: "left",
                    cursor: "pointer",
                  }}
                >
                  <div style={{ fontSize: "0.8125rem", fontWeight: 700, color: "var(--console-text-primary, #0f172a)" }}>
                    {item.notebook_title}
                  </div>
                  <div style={{ marginTop: 4, fontSize: "0.75rem", color: "var(--console-text-muted, #64748b)" }}>
                    {renderFocusSummary(item)}
                  </div>
                </button>
              ))}
            </div>
          </section>

          <section style={{ ...surfaceStyle, padding: 24 }}>
            <SectionHeader
              title={t("home.sections.focus")}
              body={t("home.sections.focusBody")}
            />
            <div style={{ display: "grid", gap: 10 }}>
              {(home?.long_term_focus ?? []).map((item) => (
                <button
                  key={item.notebook_id}
                  type="button"
                  onClick={() => openNotebook(item.notebook_id)}
                  style={{
                    padding: "12px 14px",
                    borderRadius: 14,
                    border: "1px solid rgba(15, 23, 42, 0.08)",
                    background: "rgba(255,255,255,0.9)",
                    textAlign: "left",
                    cursor: "pointer",
                  }}
                >
                  <div style={{ fontSize: "0.8125rem", fontWeight: 700, color: "var(--console-text-primary, #0f172a)" }}>
                    {item.notebook_title}
                  </div>
                  <div style={{ marginTop: 4, fontSize: "0.75rem", color: "var(--console-text-muted, #64748b)" }}>
                    {renderFocusSummary(item)}
                  </div>
                </button>
              ))}
            </div>
          </section>
        </div>
      </div>

      <CreateNotebookDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onSubmit={handleCreateSubmit}
        submitting={creating}
      />
    </div>
  );
}
