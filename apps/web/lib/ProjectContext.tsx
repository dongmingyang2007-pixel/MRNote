"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { usePathname } from "@/i18n/navigation";
import { apiGet } from "@/lib/api";

export type ProjectOption = {
  id: string;
  name: string;
};

type ProjectContextValue = {
  projectId: string;
  projects: ProjectOption[];
  loadProjects: (options?: { revalidateOnly?: boolean }) => Promise<void>;
  selectProject: (projectId: string) => Promise<void>;
};

const ProjectContext = createContext<ProjectContextValue | null>(null);

function extractProjectIdFromPath(pathname: string): string {
  const match = pathname.match(/^\/app\/assistants\/([^/]+)(?:\/|$)/);
  if (!match) {
    return "";
  }
  const candidate = decodeURIComponent(match[1]);
  return candidate === "new" ? "" : candidate;
}

function extractProjectIdFromLocation(pathname: string): string {
  if (typeof window !== "undefined") {
    const forcedProjectId = (window as Window & { __PLAYWRIGHT_FORCE_PROJECT_ID__?: string })
      .__PLAYWRIGHT_FORCE_PROJECT_ID__;
    if (forcedProjectId) {
      return forcedProjectId;
    }
    const queryProjectId = new URLSearchParams(window.location.search).get("project_id");
    if (queryProjectId) {
      return queryProjectId;
    }
  }
  return extractProjectIdFromPath(pathname);
}

export function useProjectContext(): ProjectContextValue {
  const ctx = useContext(ProjectContext);
  if (!ctx) {
    throw new Error("useProjectContext must be used within a ProjectProvider");
  }
  return ctx;
}

export function ProjectProvider({ children }: { children: ReactNode }) {
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [projectId, setProjectIdState] = useState("");
  const projectIdRef = useRef("");
  const pathname = usePathname();

  const syncProjectSelection = useCallback(async (nextProjectId: string) => {
    projectIdRef.current = nextProjectId;
    setProjectIdState(nextProjectId);
  }, []);

  const applyProjects = useCallback(
    (list: ProjectOption[], options: { revalidateOnly?: boolean } = {}) => {
      const routeProjectId = extractProjectIdFromLocation(pathname);
      const preferredProjectId = routeProjectId || projectIdRef.current;
      const currentProjectStillExists = list.some(
        (project) => project.id === preferredProjectId,
      );
      const nextProjectId = currentProjectStillExists
        ? preferredProjectId
        : (list[0]?.id ?? "");

      if (nextProjectId !== projectIdRef.current || !options.revalidateOnly) {
        projectIdRef.current = nextProjectId;
        setProjectIdState(nextProjectId);
      }
    },
    [pathname],
  );

  const loadProjects = useCallback(async (options: { revalidateOnly?: boolean } = {}) => {
    try {
      const data = await apiGet<{ items: ProjectOption[] }>("/api/v1/projects");
      const list = data.items || [];
      setProjects(list);
      applyProjects(list, options);
    } catch {
      // Auth errors handled by middleware redirect
    }
  }, [applyProjects]);

  useEffect(() => {
    let active = true;

    void apiGet<{ items: ProjectOption[] }>("/api/v1/projects")
      .then((data) => {
        if (!active) return;
        const list = data.items || [];
        setProjects(list);
        applyProjects(list, { revalidateOnly: true });
      })
      .catch(() => {
        // Silently ignore auth errors — middleware will redirect to login if needed
      });

    return () => {
      active = false;
    };
  }, [applyProjects, pathname]);

  return (
    <ProjectContext.Provider
      value={{
        projectId,
        projects,
        loadProjects,
        selectProject: syncProjectSelection,
      }}
    >
      {children}
    </ProjectContext.Provider>
  );
}
