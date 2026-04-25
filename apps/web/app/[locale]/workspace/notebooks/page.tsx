"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type KeyboardEvent,
  type MouseEvent,
} from "react";
import { useTranslations } from "next-intl";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  ArrowRight,
  BookOpen,
  Brain,
  Clock3,
  Filter,
  FileText,
  Layers,
  LayoutDashboard,
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
  getAuthStateClientSnapshot,
  getAuthStateHydrationSnapshot,
  subscribeAuthState,
} from "@/lib/auth-state";
import {
  notebookSDK,
  type CreateNotebookInput,
  type NotebookType,
} from "@/lib/notebook-sdk";
import { dispatchNotebooksChanged } from "@/lib/notebook-events";
import {
  formatNotebookDate,
  getNotebookHomeMetrics,
  type NotebookCard,
} from "@/lib/notebook-home";

type NotebookFilter = "all" | NotebookType;
type NotebookShelfId = "continue" | "sources" | "organizing" | "rest";

interface NotebookShelf {
  id: NotebookShelfId;
  title: string;
  body: string;
  notebooks: NotebookCard[];
}

const notebookTypes: NotebookType[] = ["personal", "work", "study", "scratch"];

function getKnownNotebookType(type: string): NotebookType {
  return notebookTypes.includes(type as NotebookType)
    ? (type as NotebookType)
    : "personal";
}

export default function NotebooksPage() {
  const isAuthenticated = useSyncExternalStore(
    subscribeAuthState,
    getAuthStateClientSnapshot,
    getAuthStateHydrationSnapshot,
  );
  const router = useRouter();

  useEffect(() => {
    if (isAuthenticated === null) {
      return;
    }
    if (isAuthenticated !== true) {
      router.replace("/app/notebooks/guest");
    }
  }, [isAuthenticated, router]);

  if (isAuthenticated !== true) {
    return null;
  }

  return <AuthenticatedNotebooksPage />;
}

function AuthenticatedNotebooksPage() {
  const t = useTranslations("console-notebooks");
  const router = useRouter();
  const { home, loading, reload } = useNotebookHome();
  const reduceMotion = useReducedMotion();
  const [creating, setCreating] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<NotebookFilter>("all");
  const [openingNotebookId, setOpeningNotebookId] = useState<string | null>(
    null,
  );
  const openTimeoutRef = useRef<number | null>(null);

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

  const notebookShelves = useMemo<NotebookShelf[]>(() => {
    const claimed = new Set<string>();
    const shelves: NotebookShelf[] = [];

    const addShelf = (
      id: NotebookShelfId,
      notebooks: NotebookCard[],
    ): void => {
      const uniqueNotebooks = notebooks.filter((notebook) => {
        if (claimed.has(notebook.id)) return false;
        claimed.add(notebook.id);
        return true;
      });
      if (!uniqueNotebooks.length) return;
      shelves.push({
        id,
        title: t(`library.shelf.${id}.title`),
        body: t(`library.shelf.${id}.body`),
        notebooks: uniqueNotebooks,
      });
    };

    addShelf("continue", filteredNotebooks.slice(0, 3));
    addShelf(
      "sources",
      filteredNotebooks.filter((notebook) => notebook.study_asset_count > 0),
    );
    addShelf(
      "organizing",
      filteredNotebooks.filter(
        (notebook) =>
          notebook.page_count > 0 || notebook.ai_action_count > 0,
      ),
    );
    addShelf(
      "rest",
      filteredNotebooks.filter((notebook) => !claimed.has(notebook.id)),
    );

    return shelves;
  }, [filteredNotebooks, t]);

  const visualNotebooks = filteredNotebooks.slice(0, 10);

  const dominantType = useMemo(() => {
    const visibleTypeCounts = notebookTypes
      .map((type) => ({
        type,
        count: filteredNotebooks.filter(
          (notebook) => notebook.notebook_type === type,
        ).length,
      }))
      .sort((a, b) => b.count - a.count);

    const [dominant] = visibleTypeCounts;
    return dominant && dominant.count > 0 ? dominant : null;
  }, [filteredNotebooks]);

  const librarySignals = useMemo(() => {
    const recentNotebook = filteredNotebooks[0];
    const notebooksWithSources = filteredNotebooks.filter(
      (notebook) => notebook.study_asset_count > 0,
    ).length;
    const emptyNotebooks = filteredNotebooks.filter(
      (notebook) =>
        notebook.page_count === 0 && notebook.study_asset_count === 0,
    ).length;

    return [
      {
        id: "recent",
        Icon: Clock3,
        title: t("library.signal.recent.title"),
        body: recentNotebook
          ? t("library.signal.recent.body", {
              title: recentNotebook.title || t("notebooks.untitled"),
              date: formatNotebookDate(recentNotebook.updated_at),
            })
          : t("library.signal.recent.empty"),
      },
      {
        id: "sources",
        Icon: Layers,
        title: t("library.signal.sources.title"),
        body: t("library.signal.sources.body", {
          count: notebooksWithSources,
        }),
      },
      {
        id: "empty",
        Icon: BookOpen,
        title: t("library.signal.empty.title"),
        body: t("library.signal.empty.body", {
          count: emptyNotebooks,
        }),
      },
      {
        id: "type",
        Icon: Sparkles,
        title: t("library.signal.type.title"),
        body: dominantType
          ? t("library.signal.type.body", {
              type: typeLabels[dominantType.type],
              count: dominantType.count,
            })
          : t("library.signal.type.empty"),
      },
    ];
  }, [dominantType, filteredNotebooks, t, typeLabels]);

  useEffect(() => {
    return () => {
      if (openTimeoutRef.current !== null) {
        window.clearTimeout(openTimeoutRef.current);
      }
    };
  }, []);

  const openCreateDialog = useCallback(() => {
    setCreateOpen(true);
  }, []);

  const openNotebook = useCallback(
    (notebookId: string) => {
      setOpeningNotebookId(notebookId);

      if (openTimeoutRef.current !== null) {
        window.clearTimeout(openTimeoutRef.current);
      }

      const canDelayForAnimation =
        reduceMotion !== true &&
        typeof window !== "undefined" &&
        typeof window.matchMedia === "function";

      if (!canDelayForAnimation) {
        router.push(`/app/notebooks/${notebookId}`);
        return;
      }

      openTimeoutRef.current = window.setTimeout(() => {
        router.push(`/app/notebooks/${notebookId}`);
      }, 460);
    },
    [reduceMotion, router],
  );

  const handleNotebookKeyDown = useCallback(
    (notebookId: string, event: KeyboardEvent<HTMLElement>) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      openNotebook(notebookId);
    },
    [openNotebook],
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
  const visibleCountLabel = loading
    ? t("common.loading")
    : t("library.visibleCount", { count: filteredNotebooks.length });

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
      <div className="console-page-shell workspace-dashboard-page notebook-library-page">
        <ConsolePageHeader
          className="workspace-today-bar"
          eyebrow={t("library.kicker")}
          title={t("library.title")}
          description={
            <span className="workspace-today-copy">
              <span>{t("library.description")}</span>
              <span>{visibleCountLabel}</span>
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
                onClick={() => router.push("/app")}
              >
                <LayoutDashboard size={16} />
                {t("library.backToWorkbench")}
              </GlassButton>
              <GlassButton
                type="button"
                onClick={openCreateDialog}
                disabled={creating}
                data-testid="notebooks-create-button"
              >
                <Plus size={16} />
                {t("notebooks.create")}
              </GlassButton>
            </div>
          }
        />

        <div className="workspace-workbench-grid notebook-library-workbench">
          <main className="workspace-content-column notebook-library-main">
            <section
              className="workspace-panel notebook-library-toolbar-panel"
              aria-label={t("library.toolbarLabel")}
            >
              <div className="notebook-library-toolbar">
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
              </div>
            </section>

            {loading ? (
              <div className="workspace-panel">{t("common.loading")}</div>
            ) : isTrueEmpty ? (
              <section
                className="workspace-panel notebook-library-onboarding"
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
              <section className="workspace-panel workspace-list-panel notebook-library-list-panel">
                <div className="notebook-library-shelves">
                  <AnimatePresence mode="popLayout">
                    {notebookShelves.map((shelf, shelfIndex) => (
                      <motion.section
                        key={shelf.id}
                        layout
                        className={`notebook-library-shelf is-${shelf.id}`}
                        initial={
                          reduceMotion
                            ? false
                            : { opacity: 0, y: 18, scale: 0.98 }
                        }
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        exit={{ opacity: 0, y: 12, scale: 0.98 }}
                        transition={{
                          duration: 0.28,
                          delay: reduceMotion ? 0 : shelfIndex * 0.04,
                          ease: [0.16, 1, 0.3, 1],
                        }}
                      >
                        <div className="notebook-library-shelf-header">
                          <div>
                            <h3>{shelf.title}</h3>
                            <p>{shelf.body}</p>
                          </div>
                          <span>{shelf.notebooks.length}</span>
                        </div>

                        <div className="notebook-library-book-grid">
                          {shelf.notebooks.map((notebook, notebookIndex) => {
                            const notebookType = getKnownNotebookType(
                              notebook.notebook_type,
                            );
                            const notebookTitle =
                              notebook.title || t("notebooks.untitled");
                            const notebookStats = [
                              {
                                key: "pages",
                                value: notebook.page_count,
                                Icon: FileText,
                              },
                              {
                                key: "assets",
                                value: notebook.study_asset_count,
                                Icon: Layers,
                              },
                              {
                                key: "ai",
                                value: notebook.ai_action_count,
                                Icon: Sparkles,
                              },
                            ];
                            const isOpening =
                              openingNotebookId === notebook.id;

                            return (
                              <motion.article
                                key={notebook.id}
                                layout
                                role="button"
                                tabIndex={0}
                                aria-label={`${t("library.openNotebook")}: ${notebookTitle}`}
                                className={`notebook-library-book-card is-${notebookType}${
                                  isOpening ? " is-opening" : ""
                                }`}
                                data-testid="notebook-card"
                                style={
                                  {
                                    "--book-index": notebookIndex,
                                  } as CSSProperties
                                }
                                onClick={() => openNotebook(notebook.id)}
                                onKeyDown={(event) =>
                                  handleNotebookKeyDown(notebook.id, event)
                                }
                                initial={
                                  reduceMotion
                                    ? false
                                    : {
                                        opacity: 0,
                                        y: 16,
                                        rotateX: -4,
                                      }
                                }
                                animate={{
                                  opacity: 1,
                                  y: 0,
                                  rotateX: 0,
                                }}
                                transition={{
                                  duration: 0.28,
                                  delay: reduceMotion
                                    ? 0
                                    : notebookIndex * 0.035,
                                  ease: [0.16, 1, 0.3, 1],
                                }}
                              >
                                <div className="notebook-library-book-object">
                                  <span
                                    className="notebook-library-book-shadow"
                                    aria-hidden="true"
                                  />
                                  <span
                                    className="notebook-library-book-pages"
                                    aria-hidden="true"
                                  />
                                  <div className="notebook-library-book-cover">
                                    <span
                                      className="notebook-library-book-spine"
                                      aria-hidden="true"
                                    >
                                      <span />
                                      <span />
                                      <span />
                                      <span />
                                    </span>
                                    <span
                                      className="notebook-library-book-tabs"
                                      aria-hidden="true"
                                    >
                                      <i />
                                      <i />
                                      <i />
                                    </span>
                                    <span
                                      className="notebook-library-book-bookmark"
                                      aria-hidden="true"
                                    />
                                    <span
                                      className="notebook-library-book-elastic"
                                      aria-hidden="true"
                                    />

                                    <div className="notebook-library-book-content">
                                      <div className="notebook-library-book-topline">
                                        <span className="notebook-library-type">
                                          {typeLabels[notebookType]}
                                        </span>
                                        <span className="notebook-library-book-date">
                                          {formatNotebookDate(
                                            notebook.updated_at,
                                          )}
                                        </span>
                                      </div>

                                      <div className="notebook-library-book-copy">
                                        <span
                                          className="notebook-library-book-label-rule"
                                          aria-hidden="true"
                                        />
                                        <h3>{notebookTitle}</h3>
                                        <p>
                                          {notebook.description ||
                                            t("home.notebookFallback")}
                                        </p>
                                      </div>

                                      <span
                                        className="notebook-library-book-emboss"
                                        aria-hidden="true"
                                      >
                                        <BookOpen
                                          size={30}
                                          strokeWidth={1.7}
                                        />
                                      </span>
                                    </div>
                                  </div>
                                </div>

                                <div className="notebook-library-book-footer">
                                  <div>
                                    <div
                                      className="notebook-library-book-stats"
                                      aria-label={t("library.rowStatsLabel")}
                                    >
                                      {notebookStats.map((stat) => (
                                        <span key={stat.key}>
                                          <stat.Icon
                                            size={13}
                                            aria-hidden="true"
                                          />
                                          <strong>{stat.value}</strong>
                                          <em>{t(`home.metrics.${stat.key}`)}</em>
                                        </span>
                                      ))}
                                    </div>
                                    <small>
                                      {t("home.updatedAt", {
                                        value: formatNotebookDate(
                                          notebook.updated_at,
                                        ),
                                      })}
                                    </small>
                                  </div>

                                  <div className="notebook-library-book-actions">
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
                                    <button
                                      type="button"
                                      className="notebook-library-open-button"
                                      onClick={(event) => {
                                        event.stopPropagation();
                                        openNotebook(notebook.id);
                                      }}
                                    >
                                      {isOpening
                                        ? t("library.openingNotebook")
                                        : t("library.openNotebook")}
                                      <ArrowRight size={15} />
                                    </button>
                                  </div>
                                </div>
                              </motion.article>
                            );
                          })}
                        </div>
                      </motion.section>
                    ))}
                  </AnimatePresence>
                </div>
              </section>
            ) : (
              <section className="workspace-panel">
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

          <aside
            className="notebook-library-rail"
            aria-label={t("library.contextTitle")}
          >
            <section className="workspace-panel notebook-library-visual-panel">
              <div className="workspace-panel-copy">
                <p className="workspace-panel-kicker">
                  {t("library.graphPreview")}
                </p>
                <h2>{t("library.healthTitle")}</h2>
                <p>{t("library.healthBody")}</p>
              </div>

              <div className="notebook-library-spine-stack">
                {visualNotebooks.length ? (
                  visualNotebooks.map((notebook, index) => {
                    const notebookType = getKnownNotebookType(
                      notebook.notebook_type,
                    );
                    return (
                      <button
                        key={notebook.id}
                        type="button"
                        className={`notebook-library-visual-spine is-${notebookType}`}
                        style={{ "--spine-index": index } as CSSProperties}
                        aria-label={`${t("library.openNotebook")}: ${
                          notebook.title || t("notebooks.untitled")
                        }`}
                        tabIndex={-1}
                        onClick={() => openNotebook(notebook.id)}
                      >
                        <span>{notebook.title || t("notebooks.untitled")}</span>
                      </button>
                    );
                  })
                ) : (
                  <span className="notebook-library-visual-empty" />
                )}
              </div>
            </section>

            <section className="workspace-panel notebook-library-signal-panel">
              <div className="workspace-panel-copy">
                <p className="workspace-panel-kicker">
                  {t("library.contextKicker")}
                </p>
                <h2>{t("library.contextTitle")}</h2>
                <p>{t("library.contextBody")}</p>
              </div>

              <div className="notebook-library-signal-list">
                {librarySignals.map((signal) => (
                  <div key={signal.id} className="notebook-library-signal">
                    <span className="workspace-icon-badge">
                      <signal.Icon size={15} />
                    </span>
                    <span>
                      <strong>{signal.title}</strong>
                      <small>{signal.body}</small>
                    </span>
                  </div>
                ))}
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
