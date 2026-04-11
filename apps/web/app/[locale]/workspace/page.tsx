"use client";

import { useEffect, useMemo, useState } from "react";
import { Link, useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";

import { PageTransition } from "@/components/console/PageTransition";
import { GlassButton } from "@/components/console/glass";
import type {
  PipelineConfigItem,
  PipelineResponse,
} from "@/components/console/chat-types";
import { apiGet } from "@/lib/api";
import { formatRelativeTime } from "@/lib/format-time";
import { buildProjectDisplayMap } from "@/lib/project-display";

type Project = {
  id: string;
  name: string;
  default_chat_mode?: "standard" | "omni_realtime" | "synthetic_realtime";
};

type CatalogModelSummary = {
  model_id: string;
  display_name?: string;
};

interface RecentConversation {
  id: string;
  title: string;
  updated_at: string;
}

interface DashboardConversation extends RecentConversation {
  projectId: string;
  projectName: string;
}

export default function DashboardPage() {
  const t = useTranslations("console");
  const router = useRouter();
  const [projects, setProjects] = useState<Project[]>([]);
  const [pipelineMap, setPipelineMap] = useState<Record<string, PipelineConfigItem[]>>({});
  const [catalogItems, setCatalogItems] = useState<CatalogModelSummary[]>([]);
  const [recentChats, setRecentChats] = useState<DashboardConversation[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function loadDashboard() {
      setLoading(true);

      try {
        const [projectsResponse, catalogResponse] = await Promise.all([
          apiGet<{ items: Project[] }>("/api/v1/projects"),
          apiGet<CatalogModelSummary[]>("/api/v1/models/catalog"),
        ]);

        if (cancelled) {
          return;
        }

        const projectItems = Array.isArray(projectsResponse.items)
          ? projectsResponse.items
          : [];
        setProjects(projectItems);
        setCatalogItems(Array.isArray(catalogResponse) ? catalogResponse : []);

        const [pipelineResults, conversationResults] = await Promise.all([
          Promise.allSettled(
            projectItems.map((project) =>
              apiGet<PipelineResponse>(`/api/v1/pipeline?project_id=${project.id}`),
            ),
          ),
          Promise.allSettled(
            projectItems.map((project) =>
              apiGet<RecentConversation[]>(
                `/api/v1/chat/conversations?project_id=${project.id}`,
              ),
            ),
          ),
        ]);

        if (cancelled) {
          return;
        }

        const nextPipelineMap: Record<string, PipelineConfigItem[]> = {};
        projectItems.forEach((project, index) => {
          const result = pipelineResults[index];
          nextPipelineMap[project.id] =
            result?.status === "fulfilled" && Array.isArray(result.value.items)
              ? result.value.items
              : [];
        });
        setPipelineMap(nextPipelineMap);

        const nextRecentChats: DashboardConversation[] = [];
        projectItems.forEach((project, index) => {
          const result = conversationResults[index];
          if (result?.status !== "fulfilled") {
            return;
          }
          const items = Array.isArray(result.value) ? result.value : [];
          items.slice(0, 3).forEach((conversation) => {
            nextRecentChats.push({
              ...conversation,
              projectId: project.id,
              projectName: project.name,
            });
          });
        });
        nextRecentChats.sort(
          (left, right) =>
            new Date(right.updated_at).getTime() -
            new Date(left.updated_at).getTime(),
        );
        setRecentChats(nextRecentChats.slice(0, 6));
      } catch {
        if (cancelled) {
          return;
        }
        setProjects([]);
        setPipelineMap({});
        setCatalogItems([]);
        setRecentChats([]);
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadDashboard();

    return () => {
      cancelled = true;
    };
  }, []);

  const projectLabels = useMemo(
    () => buildProjectDisplayMap(projects),
    [projects],
  );
  const catalogModelNames = useMemo(
    () =>
      new Map(
        catalogItems.map((item) => [item.model_id, item.display_name || item.model_id]),
      ),
    [catalogItems],
  );
  const projectModels = useMemo(() => {
    const map: Record<string, string> = {};
    projects.forEach((project) => {
      const items = pipelineMap[project.id] || [];
      const preferredSlotType =
        project.default_chat_mode === "omni_realtime"
          ? "realtime"
          : project.default_chat_mode === "synthetic_realtime"
            ? "llm"
            : "llm";
      const preferredSlot = items.find((item) => item.model_type === preferredSlotType);
      const llmSlot = items.find((item) => item.model_type === "llm");
      const fallbackSlot = items[0];
      const slot = preferredSlot || llmSlot || fallbackSlot;
      if (slot) {
        map[project.id] = catalogModelNames.get(slot.model_id) || slot.model_id;
      }
    });
    return map;
  }, [projects, pipelineMap, catalogModelNames]);

  const conversationCounts = useMemo(() => {
    const map: Record<string, number> = {};
    recentChats.forEach((chat) => {
      map[chat.projectId] = (map[chat.projectId] || 0) + 1;
    });
    return map;
  }, [recentChats]);

  return (
    <PageTransition>
      <div className="console-page-shell" style={{ padding: "28px 32px" }}>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
          <div>
            <h2 style={{
              fontSize: 22,
              fontWeight: 700,
              color: "var(--console-text-primary, var(--text-primary))",
              marginBottom: 4,
            }}>{t("nav.assistants")}</h2>
            <p style={{
              fontSize: 14,
              color: "var(--console-text-secondary, var(--text-secondary))",
              margin: 0,
            }}>{t("home.description")}</p>
          </div>
          <Link href="/app/assistants/new" style={{ textDecoration: "none" }}>
            <GlassButton variant="primary">{t("home.createNew")}</GlassButton>
          </Link>
        </div>

        {/* Assistant card grid */}
        {loading ? (
          <div className="home-assistant-grid">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="home-assistant-card">
                <div style={{ minHeight: 100 }} className="animate-pulse">
                  <div style={{
                    height: 14,
                    width: "66%",
                    borderRadius: 6,
                    background: "var(--console-border, var(--border))",
                    marginBottom: 12,
                  }} />
                  <div style={{
                    height: 10,
                    width: "100%",
                    borderRadius: 6,
                    background: "var(--console-border, var(--border))",
                    marginBottom: 8,
                  }} />
                  <div style={{
                    height: 10,
                    width: "75%",
                    borderRadius: 6,
                    background: "var(--console-border, var(--border))",
                  }} />
                </div>
              </div>
            ))}
          </div>
        ) : projects.length === 0 ? (
          <div className="home-assistant-grid">
            <div style={{
              gridColumn: "1 / -1",
              textAlign: "center",
              padding: "48px 0",
              color: "var(--console-text-secondary, var(--text-secondary))",
              fontSize: 14,
            }}>
              {t("home.noAssistants")}
            </div>
          </div>
        ) : (
          <div className="home-assistant-grid">
            {projects.map((project) => {
              const name = projectLabels.get(project.id) || project.name;
              const modelName = projectModels[project.id];
              const slotCount = (pipelineMap[project.id] || []).length;
              const convCount = conversationCounts[project.id] || 0;

              return (
                <div
                  key={project.id}
                  className="home-assistant-card dashboard-project-card"
                  data-testid={`dashboard-project-card-${project.id}`}
                  onClick={() => router.push(`/app/assistants/${project.id}`)}
                  style={{ cursor: "pointer" }}
                >
                  <div className="home-assistant-card-head">
                    <div className="home-assistant-card-avatar">
                      {name.charAt(0).toUpperCase()}
                    </div>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <Link
                        href={`/app/assistants/${project.id}`}
                        onClick={(e: React.MouseEvent) => e.stopPropagation()}
                        style={{
                          textDecoration: "none",
                          color: "inherit",
                          display: "inline-flex",
                          minWidth: 0,
                        }}
                      >
                        <div className="home-assistant-card-name">{name}</div>
                      </Link>
                      {modelName && (
                        <div className="home-assistant-card-model">{modelName}</div>
                      )}
                    </div>
                  </div>
                  <div className="home-assistant-card-stats">
                    <span>{t("home.modelSlots", { count: slotCount })}</span>
                    <span>{t("home.conversations", { count: convCount })}</span>
                  </div>
                  <div className="home-assistant-card-actions">
                    <Link
                      href={`/app/chat?project_id=${project.id}`}
                      onClick={(e: React.MouseEvent) => e.stopPropagation()}
                    >
                      <GlassButton variant="primary" size="small">{t("home.startChat")}</GlassButton>
                    </Link>
                    <Link
                      href={`/app/assistants/${project.id}`}
                      onClick={(e: React.MouseEvent) => e.stopPropagation()}
                    >
                      <GlassButton variant="secondary" size="small">{t("home.settings")}</GlassButton>
                    </Link>
                  </div>
                </div>
              );
            })}

            {/* Create new card */}
            <Link href="/app/assistants/new" className="home-create-card">
              <div className="home-create-card-icon">+</div>
              <span>{t("home.createCardLabel")}</span>
            </Link>
          </div>
        )}

        {/* Recent conversations section */}
        <div className="home-recent-section">
          <div className="home-recent-heading">{t("home.recentTitle")}</div>
          {recentChats.length === 0 ? (
            <div style={{
              padding: "24px 0",
              textAlign: "center",
              color: "var(--console-text-secondary, var(--text-secondary))",
              fontSize: 13,
            }}>
              {t("home.noRecent")}
            </div>
          ) : (
            recentChats.slice(0, 5).map((chat) => (
              <Link
                key={chat.id}
                href={`/app/chat?project_id=${chat.projectId}&conv=${chat.id}`}
                className="home-recent-item"
                style={{ textDecoration: "none", color: "inherit" }}
              >
                <span className="home-recent-title-text">
                  {chat.title || t("home.noRecent")}
                </span>
                <span className="home-recent-project">
                  {projectLabels.get(chat.projectId) || chat.projectName}
                </span>
                <span className="home-recent-time">
                  {formatRelativeTime(chat.updated_at, t)}
                </span>
              </Link>
            ))
          )}
        </div>
      </div>
    </PageTransition>
  );
}
