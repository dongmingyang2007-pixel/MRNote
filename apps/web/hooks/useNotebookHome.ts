"use client";

import { useCallback, useEffect, useState } from "react";

import { apiGet } from "@/lib/api";
import { NOTEBOOKS_CHANGED_EVENT } from "@/lib/notebook-events";
import { emptyHomeSummary, type HomeSummary } from "@/lib/notebook-home";

export function useNotebookHome() {
  const [home, setHome] = useState<HomeSummary>(() => emptyHomeSummary());
  const [loading, setLoading] = useState(true);

  const loadHome = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet<HomeSummary>("/api/v1/notebooks/home");
      setHome(data);
    } catch {
      setHome(emptyHomeSummary());
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

  return { home, loading, reload: loadHome };
}
