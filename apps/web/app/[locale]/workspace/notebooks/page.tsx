"use client";

import { useCallback, useMemo, useState, type MouseEvent } from "react";
import { useTranslations } from "next-intl";
import {
  ArrowRight,
  BookOpen,
  Brain,
  FileText,
  Filter,
  Plus,
  Search,
  Sparkles,
  Trash2,
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
import {
  notebookSDK,
  type CreateNotebookInput,
  type NotebookType,
} from "@/lib/notebook-sdk";
import { dispatchNotebooksChanged } from "@/lib/notebook-events";
import {
  formatNotebookDate,
  getNotebookHomeMetrics,
  type HomeAIAction,
  type HomePageItem,
} from "@/lib/notebook-home";

type NotebookFilter = "all" | NotebookType;

const notebookTypes: NotebookType[] = ["personal", "work", "study", "scratch"];

export default function NotebooksPage() {
  const t = useTranslations("console-notebooks");
  const router = useRouter();
  const { home, loading, reload } = useNotebookHome();
  const [creating, setCreating] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<NotebookFilter>("all");

  const metrics = useMemo(() => getNotebookHomeMetrics(home), [home]);

  const typeLabels = useMemo<Record<NotebookType, string>>(
    () => ({
      personal: t("notebooks.personal"),
      work: t("notebooks.work"),
      study: t("notebooks.study"),
      scratch: t("notebooks.scratch"),
    }),
    [t],
  );

  const typeCounts = useMemo(() => {
    return notebookTypes.reduce(
      (counts, type) => {
        counts[type] = home.notebooks.filter(
          (notebook) => notebook.notebook_type === type,
        ).length;
        return counts;
      },
      {
        personal: 0,
        work: 0,
        study: 0,
        scratch: 0,
      } as Record<NotebookType, number>,
    );
  }, [home.notebooks]);

  const filteredNotebooks = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return home.notebooks
      .filter((notebook) => {
        const matchesFilter =
          filter === "all" || notebook.notebook_type === filter;
        const matchesQuery =
          !normalizedQuery ||
          notebook.title.toLowerCase().includes(normalizedQuery) ||
          notebook.description.toLowerCase().includes(normalizedQuery);
        return matchesFilter && matchesQuery;
      })
      .sort(
        (a, b) =>
          new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
      );
  }, [filter, home.notebooks, query]);

  const openCreateDialog = useCallback(() => {
    setCreateOpen(true);
  }, []);

  const openNotebook = useCallback(
    (notebookId: string) => {
      router.push(`/app/notebooks/${notebookId}`);
    },
    [router],
  );

  const openPage = useCallback(
    (page: HomePageItem) => {
      router.push(`/app/notebooks/${page.notebook_id}?openPage=${page.id}`);
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

  const handlePresetCreate = useCallback(
    async (type: NotebookType, title: string) => {
      if (creating) return;
      setCreating(true);
      try {
        const notebook = await notebookSDK.create({
          title,
          notebook_type: type,
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
        void reload();
      }
    },
    [creating, reload, router, t],
  );

  const handleDelete = useCallback(
    async (id: string, event: MouseEvent<HTMLButtonElement>) => {
      event.stopPropagation();
      try {
        await notebookSDK.delete(id);
        dispatchNotebooksChanged();
        void reload();
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : t("pages.error.delete_failed");
        toast({
          title: t("pages.error.delete_failed"),
          description: message,
        });
      }
    },
    [reload, t],
  );

  const isTrueEmpty =
    !loading &&
    home.notebooks.length === 0 &&
    query.trim() === "" &&
    filter === "all";

  const filterOptions: Array<{
    id: NotebookFilter;
    label: string;
    count: number;
  }> = [
    {
      id: "all",
      label: t("library.filters.all"),
      count: home.notebooks.length,
    },
    ...notebookTypes.map((type) => ({
      id: type,
      label: typeLabels[type],
      count: typeCounts[type],
    })),
  ];

  const presets = [
    {
      id: "blank" as const,
      type: "personal" as const,
      Icon: BookOpen,
      titleKey: "home.onboarding.preset.blank.title" as const,
      bodyKey: "home.onboarding.preset.blank.body" as const,
    },
    {
      id: "work" as const,
      type: "work" as const,
      Icon: Sparkles,
      titleKey: "home.onboarding.preset.work.title" as const,
      bodyKey: "home.onboarding.preset.work.body" as const,
    },
    {
      id: "study" as const,
      type: "study" as const,
      Icon: Brain,
      titleKey: "home.onboarding.preset.study.title" as const,
      bodyKey: "home.onboarding.preset.study.body" as const,
    },
  ];

  return (
    <PageTransition>
      <div className="console-page-shell notebook-library-page">
        <ConsolePageHeader
          eyebrow={t("library.kicker")}
          title={t("library.title")}
          description={t("library.description")}
          metrics={[
            { label: t("home.metrics.notebooks"), value: metrics.notebooks },
            { label: t("home.metrics.pages"), value: metrics.pages },
            { label: t("home.metrics.assets"), value: metrics.assets },
            { label: t("home.metrics.ai"), value: metrics.ai },
          ]}
          actions={
            <GlassButton
              type="button"
              onClick={openCreateDialog}
              disabled={creating}
              data-testid="notebooks-create-button"
            >
              <Plus size={16} />
              {t("notebooks.create")}
            </GlassButton>
          }
        />

        <div className="notebook-library-layout">
          <main className="notebook-library-main">
            <section
              className="notebook-library-toolbar"
              aria-label={t("library.toolbarLabel")}
            >
              <div className="notebook-library-search">
                <Search size={17} />
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder={t("library.searchPlaceholder")}
                />
              </div>

              <div
                className="notebook-library-filters"
                aria-label={t("library.filterLabel")}
              >
                <Filter size={15} />
                {filterOptions.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    className={filter === option.id ? "is-active" : undefined}
                    aria-pressed={filter === option.id}
                    onClick={() => setFilter(option.id)}
                  >
                    <span>{option.label}</span>
                    <strong>{option.count}</strong>
                  </button>
                ))}
              </div>
            </section>

            {loading ? (
              <div className="notebook-library-panel">
                {t("common.loading")}
              </div>
            ) : isTrueEmpty ? (
              <section
                className="notebook-library-panel notebook-library-onboarding"
                data-testid="notebooks-onboarding"
              >
                <ConsoleEmptyState
                  icon={<Sparkles size={25} />}
                  title={t("home.onboarding.title")}
                  description={t("home.onboarding.body")}
                  action={
                    <GlassButton
                      type="button"
                      onClick={openCreateDialog}
                      disabled={creating}
                      data-testid="onboarding-create-button"
                    >
                      <Plus size={16} />
                      {t("home.onboarding.cta")}
                    </GlassButton>
                  }
                />
                <div className="notebook-library-preset-grid">
                  {presets.map((preset) => (
                    <button
                      key={preset.id}
                      type="button"
                      disabled={creating}
                      data-testid={`onboarding-preset-${preset.id}`}
                      onClick={() =>
                        void handlePresetCreate(preset.type, t(preset.titleKey))
                      }
                    >
                      <span className="workspace-icon-badge">
                        <preset.Icon size={17} />
                      </span>
                      <span>
                        <strong>{t(preset.titleKey)}</strong>
                        <small>{t(preset.bodyKey)}</small>
                      </span>
                    </button>
                  ))}
                </div>
              </section>
            ) : filteredNotebooks.length > 0 ? (
              <section className="notebook-card-grid">
                {filteredNotebooks.map((notebook) => {
                  const notebookType = notebookTypes.includes(
                    notebook.notebook_type as NotebookType,
                  )
                    ? (notebook.notebook_type as NotebookType)
                    : "personal";
                  return (
                    <article
                      key={notebook.id}
                      className="notebook-library-card"
                      data-testid="notebook-card"
                    >
                      <div className="notebook-library-card-head">
                        <span className="workspace-icon-badge">
                          <BookOpen size={18} />
                        </span>
                        <button
                          type="button"
                          className="notebook-library-icon-button"
                          onClick={(event) =>
                            void handleDelete(notebook.id, event)
                          }
                          aria-label={t("notebooks.delete")}
                        >
                          <Trash2 size={15} />
                        </button>
                      </div>

                      <div className="notebook-library-card-copy">
                        <span className="notebook-library-type">
                          {typeLabels[notebookType]}
                        </span>
                        <h2>{notebook.title || t("notebooks.untitled")}</h2>
                        <p>
                          {notebook.description || t("home.notebookFallback")}
                        </p>
                      </div>

                      <div className="notebook-library-stats">
                        {[
                          { key: "pages", value: notebook.page_count },
                          { key: "assets", value: notebook.study_asset_count },
                          { key: "ai", value: notebook.ai_action_count },
                        ].map((stat) => (
                          <span key={stat.key}>
                            <strong>{stat.value}</strong>
                            {t(`home.metrics.${stat.key}`)}
                          </span>
                        ))}
                      </div>

                      <div className="notebook-library-card-foot">
                        <small>
                          {t("home.updatedAt", {
                            value: formatNotebookDate(notebook.updated_at),
                          })}
                        </small>
                        <button
                          type="button"
                          className="notebook-library-open-button"
                          onClick={() => openNotebook(notebook.id)}
                        >
                          {t("library.openNotebook")}
                          <ArrowRight size={15} />
                        </button>
                      </div>
                    </article>
                  );
                })}
              </section>
            ) : (
              <section className="notebook-library-panel">
                <ConsoleEmptyState
                  icon={<Search size={24} />}
                  title={t("library.emptySearch")}
                  description={t("library.emptySearchBody")}
                  action={
                    <GlassButton
                      type="button"
                      variant="secondary"
                      onClick={() => {
                        setQuery("");
                        setFilter("all");
                      }}
                    >
                      {t("library.clearFilters")}
                    </GlassButton>
                  }
                />
              </section>
            )}
          </main>

          <aside className="notebook-library-rail">
            <section className="notebook-library-panel">
              <div className="notebook-rail-heading">
                <h2>{t("library.healthTitle")}</h2>
                <p>{t("library.healthBody")}</p>
              </div>
              <div className="notebook-health-grid">
                {notebookTypes.map((type) => (
                  <button
                    key={type}
                    type="button"
                    className={filter === type ? "is-active" : undefined}
                    onClick={() => setFilter(type)}
                  >
                    <span>{typeLabels[type]}</span>
                    <strong>{typeCounts[type]}</strong>
                  </button>
                ))}
              </div>
            </section>

            <section className="notebook-library-panel">
              <div className="notebook-rail-heading">
                <h2>{t("home.sections.recentPages")}</h2>
                <p>{t("home.sections.recentPagesBody")}</p>
              </div>
              <div className="notebook-rail-list">
                {home.recent_pages.slice(0, 5).map((page) => (
                  <button
                    key={page.id}
                    type="button"
                    onClick={() => openPage(page)}
                  >
                    <FileText size={15} />
                    <span>
                      <strong>{page.title || t("pages.untitled")}</strong>
                      <small>
                        {page.notebook_title || t("home.noNotebook")} ·{" "}
                        {formatNotebookDate(
                          page.last_edited_at || page.updated_at,
                        )}
                      </small>
                    </span>
                  </button>
                ))}
                {!loading && home.recent_pages.length === 0 ? (
                  <div className="workspace-empty-inline">
                    {t("home.empty.pages")}
                  </div>
                ) : null}
              </div>
            </section>

            <section className="notebook-library-panel">
              <div className="notebook-rail-heading">
                <h2>{t("home.sections.study")}</h2>
                <p>{t("home.sections.studyBody")}</p>
              </div>
              <div className="notebook-rail-list">
                {home.recent_study_assets.slice(0, 4).map((asset) => (
                  <button
                    key={asset.id}
                    type="button"
                    onClick={() => openNotebook(asset.notebook_id)}
                  >
                    <Brain size={15} />
                    <span>
                      <strong>{asset.title}</strong>
                      <small>
                        {asset.notebook_title || t("home.noNotebook")} ·{" "}
                        {t("study.assets.chunks", {
                          count: asset.total_chunks,
                        })}
                      </small>
                    </span>
                  </button>
                ))}
                {!loading && home.recent_study_assets.length === 0 ? (
                  <div className="workspace-empty-inline">
                    {t("home.empty.study")}
                  </div>
                ) : null}
              </div>
            </section>

            <section className="notebook-library-panel">
              <div className="notebook-rail-heading">
                <h2>{t("home.sections.aiToday")}</h2>
                <p>
                  {t("home.sections.aiTodayBody", {
                    count: home.ai_today.actions_today,
                  })}
                </p>
              </div>
              <div className="notebook-rail-list">
                {home.ai_today.recent_actions.slice(0, 4).map((action) => (
                  <button
                    key={action.id}
                    type="button"
                    onClick={() => openAction(action)}
                  >
                    <Sparkles size={15} />
                    <span>
                      <strong>{action.page_title || action.action_type}</strong>
                      <small>
                        {action.notebook_title || t("home.noNotebook")} ·{" "}
                        {formatNotebookDate(action.created_at)}
                      </small>
                    </span>
                  </button>
                ))}
                {!loading && home.ai_today.recent_actions.length === 0 ? (
                  <div className="workspace-empty-inline">
                    {t("aiActions.empty")}
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
