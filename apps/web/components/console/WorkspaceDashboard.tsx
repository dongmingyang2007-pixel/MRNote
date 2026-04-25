"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import {
  ArrowRight,
  BookOpen,
  Brain,
  Clock3,
  FileText,
  Plus,
} from "lucide-react";

import {
  ConsoleEmptyState,
  ConsolePageHeader,
} from "@/components/console/ConsolePrimitives";
import { PageTransition } from "@/components/console/PageTransition";
import { GlassButton } from "@/components/console/glass/GlassButton";
import CreateNotebookDialog from "@/components/notebook/CreateNotebookDialog";
import { useRouter } from "@/i18n/navigation";
import { toast } from "@/hooks/use-toast";
import { useNotebookHome } from "@/hooks/useNotebookHome";
import { notebookSDK, type CreateNotebookInput } from "@/lib/notebook-sdk";
import { dispatchNotebooksChanged } from "@/lib/notebook-events";
import {
  formatNotebookDate,
  getNotebookHomeMetrics,
  type FocusItem,
  type HomePageItem,
} from "@/lib/notebook-home";

export function WorkspaceDashboard() {
  const t = useTranslations("console-notebooks");
  const router = useRouter();
  const { home, loading, reload } = useNotebookHome();
  const [creating, setCreating] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);

  const metrics = useMemo(() => getNotebookHomeMetrics(home), [home]);
  const primaryPage = home.continue_writing[0] ?? home.recent_pages[0] ?? null;
  const recentPages = home.recent_pages.slice(0, 5);
  const studyAssets = home.recent_study_assets.slice(0, 4);
  const focusItems = useMemo(
    () =>
      [
        ...home.work_themes.map((item) => ({
          item,
          source: "work",
        })),
        ...home.long_term_focus.map((item) => ({
          item,
          source: "focus",
        })),
      ].slice(0, 5),
    [home.long_term_focus, home.work_themes],
  );

  const lastUpdatedAt = useMemo(() => {
    const candidates = [
      ...home.recent_pages.map(
        (page) => page.last_edited_at || page.updated_at,
      ),
      ...home.recent_study_assets.map((asset) => asset.created_at),
      ...home.ai_today.recent_actions.map((action) => action.created_at),
      ...home.notebooks.map((notebook) => notebook.updated_at),
    ].filter((value): value is string => Boolean(value));

    return (
      candidates.sort(
        (a, b) => new Date(b).getTime() - new Date(a).getTime(),
      )[0] ?? null
    );
  }, [home]);

  const openCreateDialog = useCallback(() => {
    setCreateOpen(true);
  }, []);

  const openPage = useCallback(
    (page: HomePageItem) => {
      router.push(`/app/notebooks/${page.notebook_id}?openPage=${page.id}`);
    },
    [router],
  );

  const openNotebook = useCallback(
    (notebookId: string) => {
      router.push(`/app/notebooks/${notebookId}`);
    },
    [router],
  );

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
        const message =
          error instanceof Error
            ? error.message
            : t("pages.error.create_failed");
        toast({
          title: t("pages.error.create_failed"),
          description: message,
        });
        throw error;
      } finally {
        setCreating(false);
        void reload();
      }
    },
    [creating, reload, router, t],
  );

  const renderFocusSummary = (item: FocusItem) =>
    t("home.focus.summary", {
      pages: item.page_count,
      assets: item.study_asset_count,
      ai: item.ai_action_count,
    });
  const lastUpdatedLabel = lastUpdatedAt
    ? formatNotebookDate(lastUpdatedAt)
    : t("dashboard.noRecentUpdate");

  return (
    <PageTransition>
      <div className="console-page-shell workspace-dashboard-page">
        <ConsolePageHeader
          className="workspace-today-bar"
          eyebrow={t("dashboard.kicker")}
          title={t("dashboard.title")}
          description={
            <span className="workspace-today-copy">
              <span>{t("dashboard.description")}</span>
              <span>
                {loading
                  ? t("common.loading")
                  : t("dashboard.lastUpdated", { value: lastUpdatedLabel })}
              </span>
            </span>
          }
          metrics={[
            { label: t("home.metrics.notebooks"), value: metrics.notebooks },
            { label: t("home.metrics.pages"), value: metrics.pages },
            { label: t("home.metrics.assets"), value: metrics.assets },
            { label: t("home.metrics.ai"), value: metrics.ai },
          ]}
          actions={
            <div className="dashboard-header-actions">
              <GlassButton
                type="button"
                variant="secondary"
                onClick={() => router.push("/app/notebooks")}
              >
                <BookOpen size={16} />
                {t("dashboard.openLibrary")}
              </GlassButton>
              <GlassButton
                type="button"
                onClick={
                  primaryPage ? () => openPage(primaryPage) : openCreateDialog
                }
                disabled={creating}
              >
                {primaryPage ? <FileText size={16} /> : <Plus size={16} />}
                {primaryPage
                  ? t("dashboard.continueCta")
                  : t("notebooks.create")}
              </GlassButton>
            </div>
          }
        />

        <div className="workspace-workbench-grid">
          <main className="workspace-content-column">
            <section className="workspace-panel workspace-continue-panel">
              <div className="workspace-panel-header workspace-panel-header--tight">
                <div className="workspace-panel-copy">
                  <p className="workspace-panel-kicker">
                    {t("dashboard.nowKicker")}
                  </p>
                  <h2>{t("dashboard.nowTitle")}</h2>
                  <p>{t("dashboard.nowBody")}</p>
                </div>
              </div>

              {loading ? (
                <div className="workspace-empty-inline">
                  {t("common.loading")}
                </div>
              ) : primaryPage ? (
                <button
                  type="button"
                  className="workspace-priority-card workspace-priority-card--compact"
                  onClick={() => openPage(primaryPage)}
                >
                  <span className="workspace-icon-badge">
                    <FileText size={18} />
                  </span>
                  <span className="workspace-priority-copy">
                    <strong>{primaryPage.title || t("pages.untitled")}</strong>
                    <span>
                      {primaryPage.notebook_title || t("home.noNotebook")} ·{" "}
                      {formatNotebookDate(
                        primaryPage.last_edited_at || primaryPage.updated_at,
                      )}
                    </span>
                    {primaryPage.plain_text_preview ? (
                      <small>{primaryPage.plain_text_preview}</small>
                    ) : null}
                  </span>
                  <ArrowRight size={17} />
                </button>
              ) : (
                <ConsoleEmptyState
                  icon={<FileText size={22} />}
                  title={t("home.onboarding.title")}
                  description={t("home.onboarding.body")}
                  action={
                    <GlassButton
                      type="button"
                      onClick={openCreateDialog}
                      disabled={creating}
                    >
                      <Plus size={16} />
                      {t("home.onboarding.cta")}
                    </GlassButton>
                  }
                />
              )}
            </section>

            <section className="workspace-panel workspace-list-panel">
              <div className="workspace-panel-header workspace-panel-header--tight">
                <div className="workspace-panel-copy">
                  <p className="workspace-panel-kicker">
                    {t("dashboard.recentPagesKicker")}
                  </p>
                  <h2>{t("dashboard.recentPagesTitle")}</h2>
                  <p>{t("dashboard.recentPagesBody")}</p>
                </div>
              </div>

              <div className="workspace-row-list">
                {loading ? (
                  <div className="workspace-empty-inline">
                    {t("common.loading")}
                  </div>
                ) : (
                  recentPages.map((page) => (
                    <button
                      key={page.id}
                      type="button"
                      className="workspace-row-item"
                      onClick={() => openPage(page)}
                    >
                      <span className="workspace-row-icon">
                        <FileText size={15} />
                      </span>
                      <span className="workspace-row-copy">
                        <strong>{page.title || t("pages.untitled")}</strong>
                        <small>
                          {page.notebook_title || t("home.noNotebook")} ·{" "}
                          {formatNotebookDate(
                            page.last_edited_at || page.updated_at,
                          )}
                        </small>
                        {page.plain_text_preview ? (
                          <span>{page.plain_text_preview}</span>
                        ) : null}
                      </span>
                      <ArrowRight size={15} />
                    </button>
                  ))
                )}
                {!loading && recentPages.length === 0 ? (
                  <div className="workspace-empty-inline">
                    {t("home.empty.pages")}
                  </div>
                ) : null}
              </div>
            </section>

            <section className="workspace-panel workspace-list-panel">
              <div className="workspace-panel-header workspace-panel-header--tight">
                <div className="workspace-panel-copy">
                  <p className="workspace-panel-kicker">
                    {t("dashboard.studyKicker")}
                  </p>
                  <h2>{t("home.sections.study")}</h2>
                  <p>{t("dashboard.recentAssetsBody")}</p>
                </div>
              </div>

              <div className="workspace-row-list">
                {loading ? (
                  <div className="workspace-empty-inline">
                    {t("common.loading")}
                  </div>
                ) : (
                  studyAssets.map((asset) => (
                    <button
                      key={asset.id}
                      type="button"
                      className="workspace-row-item"
                      onClick={() => openNotebook(asset.notebook_id)}
                    >
                      <span className="workspace-row-icon">
                        <Brain size={15} />
                      </span>
                      <span className="workspace-row-copy">
                        <strong>{asset.title}</strong>
                        <small>
                          {asset.notebook_title || t("home.noNotebook")} ·{" "}
                          {t("study.assets.chunks", {
                            count: asset.total_chunks,
                          })}{" "}
                          · {formatNotebookDate(asset.created_at)}
                        </small>
                      </span>
                      <ArrowRight size={15} />
                    </button>
                  ))
                )}
                {!loading && studyAssets.length === 0 ? (
                  <div className="workspace-empty-inline">
                    {t("home.empty.study")}
                  </div>
                ) : null}
              </div>
            </section>
          </main>

          <aside className="workspace-rail-stack workspace-context-rail">
            <section className="workspace-panel workspace-compact-panel">
              <div className="workspace-panel-copy">
                <p className="workspace-panel-kicker">
                  {t("dashboard.contextKicker")}
                </p>
                <h2>{t("dashboard.focusTitle")}</h2>
                <p>{t("dashboard.contextBody")}</p>
              </div>
              <div className="workspace-focus-list">
                {focusItems.map(({ item, source }, index) => (
                  <button
                    key={`${source}-${item.notebook_id}-${index}`}
                    type="button"
                    className="workspace-focus-item"
                    onClick={() => openNotebook(item.notebook_id)}
                  >
                    <Clock3 size={16} />
                    <span>
                      <strong>
                        {item.notebook_title || t("notebooks.untitled")}
                      </strong>
                      <small>{renderFocusSummary(item)}</small>
                    </span>
                  </button>
                ))}
                {!loading && focusItems.length === 0 ? (
                  <div className="workspace-empty-inline">
                    {t("dashboard.emptyFocus")}
                  </div>
                ) : null}
              </div>
            </section>
          </aside>
        </div>

        <CreateNotebookDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          onSubmit={handleCreateSubmit}
          submitting={creating}
        />
      </div>
    </PageTransition>
  );
}
