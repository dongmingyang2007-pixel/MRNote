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
  Settings,
  Sparkles,
  type LucideIcon,
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
  type HomeAIAction,
  type HomePageItem,
} from "@/lib/notebook-home";

type DashboardActivityItem =
  | {
      kind: "page";
      id: string;
      timestamp: string;
      title: string;
      label: string;
      preview: string;
      page: HomePageItem;
    }
  | {
      kind: "ai";
      id: string;
      timestamp: string;
      title: string;
      label: string;
      preview: string;
      action: HomeAIAction;
    };

interface CommandCard {
  key: string;
  title: string;
  body: string;
  Icon: LucideIcon;
  onClick: () => void;
}

export function WorkspaceDashboard() {
  const t = useTranslations("console-notebooks");
  const router = useRouter();
  const { home, loading, reload } = useNotebookHome();
  const [creating, setCreating] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);

  const metrics = useMemo(() => getNotebookHomeMetrics(home), [home]);
  const primaryPage = home.continue_writing[0] ?? home.recent_pages[0] ?? null;
  const primaryAsset = home.recent_study_assets[0] ?? null;

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

  const openAction = useCallback(
    (action: HomeAIAction) => {
      if (action.notebook_id && action.page_id) {
        router.push(
          `/app/notebooks/${action.notebook_id}?openPage=${action.page_id}`,
        );
        return;
      }
      if (action.notebook_id) {
        router.push(`/app/notebooks/${action.notebook_id}`);
      }
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

  const activityItems = useMemo<DashboardActivityItem[]>(() => {
    const pages = home.recent_pages.map((page) => ({
      kind: "page" as const,
      id: page.id,
      timestamp: page.last_edited_at || page.updated_at,
      title: page.title || t("pages.untitled"),
      label: `${t("dashboard.activityPageLabel")} · ${
        page.notebook_title || t("home.noNotebook")
      }`,
      preview: page.plain_text_preview,
      page,
    }));
    const actions = home.ai_today.recent_actions.map((action) => ({
      kind: "ai" as const,
      id: action.id,
      timestamp: action.created_at,
      title: action.page_title || action.action_type,
      label: `${t("dashboard.activityAiLabel")} · ${
        action.notebook_title || t("home.noNotebook")
      }`,
      preview: action.output_summary || action.action_type,
      action,
    }));

    return [...pages, ...actions]
      .sort(
        (a, b) =>
          new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
      )
      .slice(0, 7);
  }, [home, t]);

  const commandCards = useMemo<CommandCard[]>(
    () => [
      {
        key: "library",
        title: t("dashboard.commands.libraryTitle"),
        body: t("dashboard.commands.libraryBody"),
        Icon: BookOpen,
        onClick: () => router.push("/app/notebooks"),
      },
      {
        key: "settings",
        title: t("dashboard.commands.settingsTitle"),
        body: t("dashboard.commands.settingsBody"),
        Icon: Settings,
        onClick: () => router.push("/app/settings"),
      },
      {
        key: "new",
        title: t("dashboard.commands.newTitle"),
        body: t("dashboard.commands.newBody"),
        Icon: Plus,
        onClick: openCreateDialog,
      },
    ],
    [openCreateDialog, router, t],
  );

  const renderFocusSummary = (item: FocusItem) =>
    t("home.focus.summary", {
      pages: item.page_count,
      assets: item.study_asset_count,
      ai: item.ai_action_count,
    });

  return (
    <PageTransition>
      <div className="console-page-shell workspace-dashboard-page">
        <ConsolePageHeader
          eyebrow={t("dashboard.kicker")}
          title={t("dashboard.title")}
          description={t("dashboard.description")}
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

        <div className="workspace-overview-grid">
          <section className="workspace-panel workspace-priority-panel">
            <div className="workspace-panel-copy">
              <p className="workspace-panel-kicker">
                {t("dashboard.nowKicker")}
              </p>
              <h2>{t("dashboard.nowTitle")}</h2>
              <p>{t("dashboard.nowBody")}</p>
            </div>

            {loading ? (
              <div className="workspace-empty-inline">
                {t("common.loading")}
              </div>
            ) : primaryPage ? (
              <button
                type="button"
                className="workspace-priority-card"
                onClick={() => openPage(primaryPage)}
              >
                <span className="workspace-icon-badge">
                  <FileText size={19} />
                </span>
                <span className="workspace-priority-copy">
                  <strong>{primaryPage.title || t("pages.untitled")}</strong>
                  <span>
                    {primaryPage.notebook_title || t("home.noNotebook")}
                  </span>
                  {primaryPage.plain_text_preview ? (
                    <small>{primaryPage.plain_text_preview}</small>
                  ) : null}
                </span>
                <ArrowRight size={18} />
              </button>
            ) : (
              <ConsoleEmptyState
                icon={<Sparkles size={24} />}
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

          <div className="workspace-command-grid">
            {commandCards.map((card) => (
              <button
                key={card.key}
                type="button"
                className="workspace-command-card"
                onClick={card.onClick}
              >
                <span className="workspace-icon-badge">
                  <card.Icon size={18} />
                </span>
                <span>
                  <strong>{card.title}</strong>
                  <small>{card.body}</small>
                </span>
                <ArrowRight size={16} />
              </button>
            ))}
          </div>
        </div>

        <div className="workspace-main-grid">
          <section className="workspace-panel">
            <div className="workspace-panel-header">
              <div className="workspace-panel-copy">
                <p className="workspace-panel-kicker">
                  {t("dashboard.activityKicker")}
                </p>
                <h2>{t("dashboard.activityTitle")}</h2>
                <p>{t("dashboard.activityBody")}</p>
              </div>
            </div>

            <div className="workspace-activity-list">
              {activityItems.map((item) => (
                <button
                  key={`${item.kind}-${item.id}`}
                  type="button"
                  className="workspace-activity-item"
                  onClick={() =>
                    item.kind === "page"
                      ? openPage(item.page)
                      : openAction(item.action)
                  }
                >
                  <span
                    className={`workspace-activity-kind is-${item.kind}`}
                    aria-hidden="true"
                  >
                    {item.kind === "page" ? (
                      <FileText size={15} />
                    ) : (
                      <Sparkles size={15} />
                    )}
                  </span>
                  <span className="workspace-activity-copy">
                    <strong>{item.title}</strong>
                    <span>
                      {item.label} · {formatNotebookDate(item.timestamp)}
                    </span>
                    {item.preview ? <small>{item.preview}</small> : null}
                  </span>
                </button>
              ))}
              {!loading && activityItems.length === 0 ? (
                <div className="workspace-empty-inline">
                  {t("dashboard.emptyActivity")}
                </div>
              ) : null}
            </div>
          </section>

          <aside className="workspace-rail-stack">
            <section className="workspace-panel workspace-compact-panel">
              <div className="workspace-panel-copy">
                <p className="workspace-panel-kicker">
                  {t("dashboard.todayKicker")}
                </p>
                <h2>{t("dashboard.todayTitle")}</h2>
                <p>
                  {t("home.sections.aiTodayBody", {
                    count: home.ai_today.actions_today,
                  })}
                </p>
              </div>
              <div className="workspace-pill-row">
                {home.ai_today.top_action_types.length > 0 ? (
                  home.ai_today.top_action_types.map((item) => (
                    <span key={item.action_type} className="workspace-pill">
                      {item.action_type}
                      <strong>{item.count}</strong>
                    </span>
                  ))
                ) : (
                  <span className="workspace-empty-inline">
                    {t("aiActions.empty")}
                  </span>
                )}
              </div>
            </section>

            <section className="workspace-panel workspace-compact-panel">
              <div className="workspace-panel-copy">
                <p className="workspace-panel-kicker">
                  {t("dashboard.studyKicker")}
                </p>
                <h2>{t("home.sections.study")}</h2>
              </div>
              {primaryAsset ? (
                <button
                  type="button"
                  className="workspace-focus-item"
                  onClick={() => openNotebook(primaryAsset.notebook_id)}
                >
                  <Brain size={16} />
                  <span>
                    <strong>{primaryAsset.title}</strong>
                    <small>
                      {primaryAsset.notebook_title || t("home.noNotebook")} ·{" "}
                      {t("study.assets.chunks", {
                        count: primaryAsset.total_chunks,
                      })}
                    </small>
                  </span>
                </button>
              ) : (
                <div className="workspace-empty-inline">
                  {t("home.empty.study")}
                </div>
              )}
            </section>

            <section className="workspace-panel workspace-compact-panel">
              <div className="workspace-panel-copy">
                <p className="workspace-panel-kicker">
                  {t("home.sections.themes")}
                </p>
                <h2>{t("dashboard.focusTitle")}</h2>
              </div>
              <div className="workspace-focus-list">
                {[
                  ...home.work_themes.map((item) => ({
                    item,
                    source: "work",
                  })),
                  ...home.long_term_focus.map((item) => ({
                    item,
                    source: "focus",
                  })),
                ]
                  .slice(0, 4)
                  .map(({ item, source }, index) => (
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
                {!loading &&
                home.work_themes.length + home.long_term_focus.length === 0 ? (
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
