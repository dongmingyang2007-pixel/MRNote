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

const EMPTY_RELATED_RESPONSE: RelatedResponse = { pages: [], memory: [] };

export function useRelatedPages(pageId: string | null) {
  const [state, setState] = useState<{
    pageId: string;
    data: RelatedResponse;
  } | null>(null);

  useEffect(() => {
    if (!pageId) {
      return;
    }
    let cancelled = false;
    void apiGet<RelatedResponse>(`/api/v1/pages/${pageId}/related?limit=5`)
      .then((data) => {
        if (!cancelled) setState({ pageId, data });
      })
      .catch(() => {
        if (!cancelled) setState({ pageId, data: EMPTY_RELATED_RESPONSE });
      });
    return () => { cancelled = true; };
  }, [pageId]);

  if (!pageId || state?.pageId !== pageId) {
    return EMPTY_RELATED_RESPONSE;
  }
  return state.data;
}
