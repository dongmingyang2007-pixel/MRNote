"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

export interface RelatedPage {
  id: string;
  notebook_id: string;
  title: string;
  score: number;
  reason: "semantic" | "shared_subject";
}

export interface RelatedMemory {
  id: string;
  content: string;
  score: number;
  reason: string;
}

export interface RelatedResponse {
  pages: RelatedPage[];
  memory: RelatedMemory[];
}

export function useRelatedPages(pageId: string | null) {
  const [data, setData] = useState<RelatedResponse>({ pages: [], memory: [] });

  useEffect(() => {
    if (!pageId) {
      setData({ pages: [], memory: [] });
      return;
    }
    let cancelled = false;
    void apiGet<RelatedResponse>(`/api/v1/pages/${pageId}/related?limit=5`)
      .then((r) => { if (!cancelled) setData(r); })
      .catch(() => { if (!cancelled) setData({ pages: [], memory: [] }); });
    return () => { cancelled = true; };
  }, [pageId]);

  return data;
}
