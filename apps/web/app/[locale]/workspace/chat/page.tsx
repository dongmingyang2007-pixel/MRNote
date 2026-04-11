"use client";

import {
  Suspense,
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
} from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { usePathname, useRouter } from "@/i18n/navigation";
import { ChatInterface } from "@/components/console/ChatInterface";
import { PageTransition } from "@/components/console/PageTransition";
import { apiDelete, apiGet, apiPost } from "@/lib/api";
import { formatRelativeTime } from "@/lib/format-time";
import { buildProjectDisplayMap } from "@/lib/project-display";

type ProjectOption = {
  id: string;
  name: string;
};

type ConversationItem = {
  id: string;
  project_id: string;
  title: string;
  updated_at: string;
};

type LoadedMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at?: string;
};

const CHAT_SIDEBAR_STYLE = {
  width: 260,
  flexShrink: 0,
  overflow: "hidden",
  padding: 16,
  borderRadius: 20,
  boxSizing: "border-box",
  background: "rgba(255, 255, 255, 0.72)",
  border: "1px solid rgba(15, 23, 42, 0.08)",
  boxShadow: "0 18px 50px rgba(15, 23, 42, 0.08)",
  backdropFilter: "blur(18px)",
} as const;

const CHAT_SIDEBAR_BODY_STYLE = {
  display: "flex",
  flexDirection: "column",
  gap: 10,
  minHeight: 0,
  flex: 1,
} as const;

const CHAT_SIDEBAR_SEARCH_BUTTON_STYLE = {
  border: "none",
  background: "transparent",
  padding: 0,
  margin: 0,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  cursor: "pointer",
  color: "inherit",
} as const;

const GENERIC_CONVERSATION_TITLES = new Set([
  "",
  "new conversation",
  "新对话",
  "新建对话",
]);
const CONVERSATION_PREVIEW_MAX = 42;

function normalizeConversationPreview(text: string): string {
  const normalized = text.trim().replace(/\s+/g, " ");
  if (!normalized) {
    return "";
  }
  if (normalized.length <= CONVERSATION_PREVIEW_MAX) {
    return normalized;
  }
  return `${normalized.slice(0, CONVERSATION_PREVIEW_MAX - 1)}…`;
}

function getLatestConversationPreview(messages: LoadedMessage[]): string {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const preview = normalizeConversationPreview(messages[index]?.content ?? "");
    if (preview) {
      return preview;
    }
  }
  return "";
}

function isGenericConversationTitle(title: string): boolean {
  return GENERIC_CONVERSATION_TITLES.has(title.trim().toLowerCase());
}

function sortConversationsByUpdatedAt(
  items: ConversationItem[],
): ConversationItem[] {
  return [...items].sort(
    (left, right) =>
      new Date(right.updated_at).getTime() -
      new Date(left.updated_at).getTime(),
  );
}

function ChatPageContent() {
  const t = useTranslations("console-chat");
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const requestedProjectId = searchParams.get("project_id") || "";
  const requestedConversationId = searchParams.get("conv") || "";

  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<
    string | null
  >(null);
  const [conversationSummaries, setConversationSummaries] = useState<
    Record<string, string>
  >({});
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [conversationLoadState, setConversationLoadState] = useState<
    "idle" | "loading" | "ready" | "error"
  >("idle");
  const [isCreatingConversation, setIsCreatingConversation] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchExpanded, setSearchExpanded] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    conversationId: string;
  } | null>(null);

  const selectedProjectIdRef = useRef("");
  const conversationRequestSeqRef = useRef(0);
  const createConversationRequestSeqRef = useRef(0);
  const createConversationInFlightRef = useRef(0);
  const autoCreateProjectRef = useRef<string | null>(null);
  const pendingConversationUrlSyncRef = useRef<string | null>(null);
  const projectRetryTimeoutRef = useRef<number | null>(null);
  const conversationRetryTimeoutRef = useRef<number | null>(null);
  const shouldSyncChatUrlRef = useRef(
    Boolean(requestedProjectId || requestedConversationId),
  );

  useEffect(() => {
    selectedProjectIdRef.current = selectedProjectId;
  }, [selectedProjectId]);

  const clearProjectRetry = useCallback(() => {
    if (projectRetryTimeoutRef.current !== null) {
      window.clearTimeout(projectRetryTimeoutRef.current);
      projectRetryTimeoutRef.current = null;
    }
  }, []);

  const clearConversationRetry = useCallback(() => {
    if (conversationRetryTimeoutRef.current !== null) {
      window.clearTimeout(conversationRetryTimeoutRef.current);
      conversationRetryTimeoutRef.current = null;
    }
  }, []);

  const projectLabels = useMemo(
    () => buildProjectDisplayMap(projects),
    [projects],
  );
  const settledConversationId = useMemo(() => {
    return activeConversationId ?? null;
  }, [activeConversationId]);

  const deferredSearch = useDeferredValue(searchQuery);

  useEffect(() => {
    if (requestedProjectId || requestedConversationId) {
      shouldSyncChatUrlRef.current = true;
    }
  }, [requestedConversationId, requestedProjectId]);

  const replaceChatUrl = useCallback(
    (
      projectId: string,
      conversationId: string | null,
      options?: { force?: boolean },
    ) => {
      if (options?.force) {
        shouldSyncChatUrlRef.current = true;
      }
      if (!shouldSyncChatUrlRef.current) {
        return false;
      }

      const params = new URLSearchParams(searchParams.toString());
      if (projectId) {
        params.set("project_id", projectId);
      } else {
        params.delete("project_id");
      }
      if (conversationId) {
        params.set("conv", conversationId);
      } else {
        params.delete("conv");
      }

      const nextQuery = params.toString();
      const nextHref = nextQuery ? `${pathname}?${nextQuery}` : pathname;
      const currentQuery = searchParams.toString();
      const currentHref = currentQuery
        ? `${pathname}?${currentQuery}`
        : pathname;
      if (nextHref !== currentHref) {
        router.replace(nextHref);
        return true;
      }

      return false;
    },
    [pathname, router, searchParams],
  );

  const loadConversations = useCallback(async (projectId: string) => {
    if (!projectId) {
      clearConversationRetry();
      setConversations([]);
      setConversationLoadState("idle");
      return [];
    }

    const requestId = conversationRequestSeqRef.current + 1;
    conversationRequestSeqRef.current = requestId;
    setConversationLoadState("loading");

    try {
      const data = await apiGet<ConversationItem[]>(
        `/api/v1/chat/conversations?project_id=${projectId}`,
      );
      if (conversationRequestSeqRef.current !== requestId) {
        return [];
      }
      const list = sortConversationsByUpdatedAt(
        Array.isArray(data) ? data : [],
      );
      setConversations(list);
      setConversationLoadState("ready");
      clearConversationRetry();
      return list;
    } catch {
      if (conversationRequestSeqRef.current === requestId) {
        setConversationLoadState("error");
        clearConversationRetry();
        conversationRetryTimeoutRef.current = window.setTimeout(() => {
          if (selectedProjectIdRef.current === projectId) {
            void loadConversations(projectId);
          }
        }, 2000);
      }
      return [];
    }
  }, [clearConversationRetry]);

  const createConversation = useCallback(
    async (
      projectId: string,
      options?: {
        syncUrl?: boolean;
      },
    ) => {
      if (!projectId) {
        return null;
      }

      const requestId = createConversationRequestSeqRef.current + 1;
      createConversationRequestSeqRef.current = requestId;
      conversationRequestSeqRef.current += 1;
      createConversationInFlightRef.current += 1;
      setIsCreatingConversation(true);
      try {
        const created = await apiPost<ConversationItem>(
          "/api/v1/chat/conversations",
          {
            project_id: projectId,
            title: "",
          },
        );
        if (!created || selectedProjectIdRef.current !== projectId) {
          return created;
        }

        setConversations((prev) =>
          sortConversationsByUpdatedAt([
            created,
            ...prev.filter((item) => item.id !== created.id),
          ]),
        );
        if (requestId === createConversationRequestSeqRef.current) {
          setActiveConversationId(created.id);
          const didSyncUrl = replaceChatUrl(projectId, created.id, {
            force: options?.syncUrl,
          });
          pendingConversationUrlSyncRef.current = didSyncUrl ? created.id : null;
          autoCreateProjectRef.current = projectId;
        }
        return created;
      } catch {
        autoCreateProjectRef.current = null;
        return null;
      } finally {
        createConversationInFlightRef.current = Math.max(
          0,
          createConversationInFlightRef.current - 1,
        );
        if (
          selectedProjectIdRef.current === projectId &&
          createConversationInFlightRef.current === 0
        ) {
          setIsCreatingConversation(false);
        }
      }
    },
    [replaceChatUrl],
  );

  useEffect(() => {
    let active = true;
    const loadProjects = async () => {
      if (!active) {
        return;
      }

      setLoadingProjects(true);

      try {
        const data = await apiGet<{ items: ProjectOption[] }>("/api/v1/projects");
        if (!active) {
          return;
        }
        const list = Array.isArray(data.items) ? data.items : [];
        setProjects(list);
        clearProjectRetry();
      } catch {
        if (!active) {
          return;
        }
        clearProjectRetry();
        projectRetryTimeoutRef.current = window.setTimeout(() => {
          void loadProjects();
        }, 2000);
      } finally {
        if (active) {
          setLoadingProjects(false);
        }
      }
    };

    void loadProjects();

    return () => {
      active = false;
      clearProjectRetry();
    };
  }, [clearProjectRetry]);

  useEffect(() => {
    if (loadingProjects) {
      return;
    }

    const availableProjectIds = new Set(projects.map((project) => project.id));
    const nextProjectId = availableProjectIds.has(requestedProjectId)
      ? requestedProjectId
      : (projects[0]?.id ?? "");

    if (!nextProjectId) {
      setSelectedProjectId("");
      setActiveConversationId(null);
      setConversations([]);
      return;
    }

    if (nextProjectId !== selectedProjectId) {
      setSelectedProjectId(nextProjectId);
      setActiveConversationId(null);
      autoCreateProjectRef.current = null;
      return;
    }

    if (requestedProjectId !== nextProjectId) {
      replaceChatUrl(nextProjectId, activeConversationId);
    }
  }, [
    activeConversationId,
    loadingProjects,
    projects,
    replaceChatUrl,
    requestedProjectId,
    selectedProjectId,
  ]);

  useEffect(() => {
    if (!selectedProjectId) {
      clearConversationRetry();
      setConversations([]);
      setConversationLoadState("idle");
      setActiveConversationId(null);
      return;
    }

    void loadConversations(selectedProjectId);
    return () => {
      clearConversationRetry();
    };
  }, [clearConversationRetry, loadConversations, selectedProjectId]);

  useEffect(() => {
    if (!selectedProjectId || conversationLoadState !== "ready") {
      return;
    }

    const availableConversationIds = new Set(
      conversations.map((conversation) => conversation.id),
    );
    const pendingConversationId = pendingConversationUrlSyncRef.current;

    if (
      pendingConversationId &&
      requestedConversationId === pendingConversationId
    ) {
      pendingConversationUrlSyncRef.current = null;
    }

    if (
      pendingConversationId &&
      requestedConversationId !== pendingConversationId &&
      activeConversationId &&
      availableConversationIds.has(activeConversationId)
    ) {
      return;
    }

    if (
      requestedConversationId &&
      availableConversationIds.has(requestedConversationId)
    ) {
      if (activeConversationId !== requestedConversationId) {
        setActiveConversationId(requestedConversationId);
      }
      return;
    }

    if (
      activeConversationId &&
      availableConversationIds.has(activeConversationId)
    ) {
      if (requestedConversationId !== activeConversationId) {
        replaceChatUrl(selectedProjectId, activeConversationId);
      }
      return;
    }

    if (conversations.length > 0) {
      const nextConversationId = conversations[0]?.id ?? null;
      setActiveConversationId(nextConversationId);
      const didSyncUrl = replaceChatUrl(selectedProjectId, nextConversationId);
      pendingConversationUrlSyncRef.current = didSyncUrl
        ? nextConversationId
        : null;
      return;
    }

    if (
      !isCreatingConversation &&
      autoCreateProjectRef.current !== selectedProjectId
    ) {
      autoCreateProjectRef.current = selectedProjectId;
      void createConversation(selectedProjectId, {
        syncUrl: shouldSyncChatUrlRef.current,
      });
    }
  }, [
    activeConversationId,
    conversations,
    conversationLoadState,
    createConversation,
    isCreatingConversation,
    replaceChatUrl,
    requestedConversationId,
    selectedProjectId,
  ]);

  const handleProjectChange = useCallback(
    (event: ChangeEvent<HTMLSelectElement>) => {
      const nextProjectId = event.target.value;
      if (!nextProjectId) {
        return;
      }

      if (nextProjectId === selectedProjectId) {
        void loadConversations(nextProjectId);
        return;
      }

      setSelectedProjectId(nextProjectId);
      setActiveConversationId(null);
      setConversations([]);
      setConversationLoadState("idle");
      setIsCreatingConversation(false);
      autoCreateProjectRef.current = null;
      pendingConversationUrlSyncRef.current = null;
      replaceChatUrl(nextProjectId, null, { force: true });
    },
    [loadConversations, replaceChatUrl, selectedProjectId],
  );

  const handleConversationSelect = useCallback(
    (conversationId: string) => {
      setActiveConversationId(conversationId);
      const didSyncUrl = replaceChatUrl(selectedProjectId, conversationId, {
        force: true,
      });
      pendingConversationUrlSyncRef.current = didSyncUrl
        ? conversationId
        : null;
    },
    [replaceChatUrl, selectedProjectId],
  );

  const handleConversationCreate = useCallback(() => {
    if (!selectedProjectId || isCreatingConversation) {
      return;
    }
    autoCreateProjectRef.current = selectedProjectId;
    void createConversation(selectedProjectId, { syncUrl: true });
  }, [createConversation, isCreatingConversation, selectedProjectId]);

  const handleConversationActivity = useCallback(
    (payload: { conversationId: string; previewText: string }) => {
      const preview = normalizeConversationPreview(payload.previewText);
      if (preview) {
        setConversationSummaries((prev) => {
          if (prev[payload.conversationId] === preview) {
            return prev;
          }
          return {
            ...prev,
            [payload.conversationId]: preview,
          };
        });
      }

      const nowIso = new Date().toISOString();
      setConversations((prev) => {
        const current = prev.find(
          (conversation) => conversation.id === payload.conversationId,
        );
        if (!current) {
          return prev;
        }

        const updated: ConversationItem = {
          ...current,
          updated_at: nowIso,
        };
        return [updated, ...prev.filter((item) => item.id !== updated.id)];
      });
    },
    [],
  );

  const handleConversationLoaded = useCallback(
    (payload: { conversationId: string; messages: LoadedMessage[] }) => {
      const preview = getLatestConversationPreview(payload.messages);
      if (!preview) {
        return;
      }

      setConversationSummaries((prev) => {
        if (prev[payload.conversationId] === preview) {
          return prev;
        }
        return {
          ...prev,
          [payload.conversationId]: preview,
        };
      });
    },
    [],
  );

  const renderConversationTitle = useCallback(
    (conversation: ConversationItem) => {
      if (!isGenericConversationTitle(conversation.title)) {
        return conversation.title;
      }
      return t("newConversation");
    },
    [t],
  );

  const renderConversationPreview = useCallback(
    (conversation: ConversationItem) => {
      const preview = conversationSummaries[conversation.id] || "";
      return preview || t("noPreview");
    },
    [conversationSummaries, t],
  );

  const filteredConversations = useMemo(() => {
    if (!deferredSearch.trim()) return conversations;
    const q = deferredSearch.trim().toLowerCase();
    return conversations.filter((c) => {
      const title = renderConversationTitle(c).toLowerCase();
      const preview = (conversationSummaries[c.id] || "").toLowerCase();
      return title.includes(q) || preview.includes(q);
    });
  }, [
    conversationSummaries,
    conversations,
    deferredSearch,
    renderConversationTitle,
  ]);

  const handleDeleteConversation = useCallback(
    async (conversationId: string) => {
      try {
        await apiDelete(`/api/v1/chat/conversations/${conversationId}`);
        setConversations((prev) => prev.filter((c) => c.id !== conversationId));
        if (activeConversationId === conversationId) {
          const remaining = conversations.filter(
            (c) => c.id !== conversationId,
          );
          const next = remaining[0]?.id ?? null;
          setActiveConversationId(next);
          const didSyncUrl = replaceChatUrl(selectedProjectId, next, {
            force: true,
          });
          pendingConversationUrlSyncRef.current = didSyncUrl ? next : null;
        }
      } catch {
        /* silent */
      }
      setContextMenu(null);
    },
    [activeConversationId, conversations, replaceChatUrl, selectedProjectId],
  );

  const handleContextMenu = useCallback(
    (e: React.MouseEvent, conversationId: string) => {
      e.preventDefault();
      setContextMenu({ x: e.clientX, y: e.clientY, conversationId });
    },
    [],
  );

  useEffect(() => {
    if (!contextMenu) return;
    const close = () => setContextMenu(null);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [contextMenu]);

  return (
    <div className="chat-page-root">
      <PageTransition>
        <div className="chat-page-layout chat-page">
          <div
            className={`chat-sidebar-drawer-backdrop${drawerOpen ? " is-open" : ""}`}
            onClick={() => setDrawerOpen(false)}
          />

          {contextMenu && (
            <div
              className="chat-sidebar-context-menu"
              style={{ left: contextMenu.x, top: contextMenu.y }}
            >
              <button
                type="button"
                className="chat-sidebar-context-item is-danger"
                onClick={() =>
                  handleDeleteConversation(contextMenu.conversationId)
                }
              >
                {t("deleteConversation")}
              </button>
            </div>
          )}

          <aside
            className={`chat-sidebar${drawerOpen ? " is-open" : ""}`}
            aria-label="Conversation sidebar"
            style={CHAT_SIDEBAR_STYLE}
          >
            <div className="chat-sidebar-header">
              <div className="chat-sidebar-header-copy">
                <div className="chat-sidebar-kicker">会话</div>
                <div className="chat-sidebar-project">
                  {projectLabels.get(selectedProjectId) ||
                    projects.find((project) => project.id === selectedProjectId)
                      ?.name ||
                    t("selectAssistant")}
                </div>
              </div>
              <div
                className="chat-sidebar-count"
                aria-label="Conversation count"
              >
                {filteredConversations.length}
              </div>
            </div>

            <div className="chat-sidebar-body" style={CHAT_SIDEBAR_BODY_STYLE}>
              <div
                className="chat-sidebar-search"
                aria-label={t("searchPlaceholder")}
              >
                <button
                  type="button"
                  className="chat-sidebar-search-toggle"
                  onClick={() => setSearchExpanded((p) => !p)}
                  aria-expanded={searchExpanded}
                  aria-label={t("searchPlaceholder")}
                  style={CHAT_SIDEBAR_SEARCH_BUTTON_STYLE}
                >
                  <svg
                    className="chat-sidebar-search-icon"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <circle cx="11" cy="11" r="8" />
                    <line x1="21" y1="21" x2="16.65" y2="16.65" />
                  </svg>
                </button>
                {searchExpanded && (
                  <input
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder={t("searchPlaceholder")}
                    autoFocus
                  />
                )}
              </div>

              <div className="chat-sidebar-header-row">
                <select
                  className="inline-topbar-project-select"
                  value={selectedProjectId}
                  onChange={handleProjectChange}
                  disabled={loadingProjects || projects.length === 0}
                  aria-label={t("selectAssistant")}
                >
                  {projects.length === 0 ? (
                    <option value="">{t("selectAssistant")}</option>
                  ) : null}
                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {projectLabels.get(project.id) || project.name}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="chat-sidebar-new-btn chat-sidebar-new"
                  onClick={handleConversationCreate}
                  disabled={
                    !selectedProjectId ||
                    isCreatingConversation ||
                    loadingProjects
                  }
                  title={t("newConversation")}
                >
                  +
                </button>
              </div>

              <div className="chat-sidebar-list">
                {conversationLoadState === "loading" ? (
                  <div className="chat-sidebar-empty">...</div>
                ) : filteredConversations.length === 0 ? (
                  <div className="chat-sidebar-empty">
                    {searchQuery
                      ? t("searchPlaceholder")
                      : t("noConversations")}
                  </div>
                ) : (
                  filteredConversations.map((conversation) => {
                    const isActive = conversation.id === activeConversationId;
                    return (
                      <button
                        key={conversation.id}
                        type="button"
                        className={`chat-sidebar-item${isActive ? " is-active" : ""}`}
                        onClick={() => {
                          handleConversationSelect(conversation.id);
                          setDrawerOpen(false);
                        }}
                        onContextMenu={(e) =>
                          handleContextMenu(e, conversation.id)
                        }
                      >
                        <div className="chat-sidebar-item-row1">
                          <div className="chat-sidebar-item-avatar">
                            {renderConversationTitle(
                              conversation,
                            )[0]?.toUpperCase() || "?"}
                          </div>
                          <div className="chat-sidebar-item-title">
                            {renderConversationTitle(conversation)}
                          </div>
                        </div>
                        <div className="chat-sidebar-item-row2">
                          <span className="chat-sidebar-item-preview">
                            {renderConversationPreview(conversation)}
                          </span>
                          <span className="chat-sidebar-item-time">
                            {formatRelativeTime(conversation.updated_at, t)}
                          </span>
                        </div>
                      </button>
                    );
                  })
                )}
              </div>
            </div>
          </aside>

          <main className="chat-main" aria-label={t("title")}>
            <button
              type="button"
              className="chat-sidebar-hamburger"
              onClick={() => setDrawerOpen(true)}
              title={t("drawerOpen")}
            >
              <svg
                viewBox="0 0 24 24"
                width={20}
                height={20}
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
              >
                <line x1="3" y1="6" x2="21" y2="6" />
                <line x1="3" y1="12" x2="21" y2="12" />
                <line x1="3" y1="18" x2="21" y2="18" />
              </svg>
            </button>
            <ChatInterface
              conversationId={settledConversationId}
              projectId={selectedProjectId}
              isConversationPending={isCreatingConversation}
              onConversationActivity={handleConversationActivity}
              onConversationLoaded={handleConversationLoaded}
            />
          </main>
        </div>
      </PageTransition>
    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense
      fallback={
        <PageTransition>
          <div className="p-6">
            <div className="console-empty">...</div>
          </div>
        </PageTransition>
      }
    >
      <ChatPageContent />
    </Suspense>
  );
}
