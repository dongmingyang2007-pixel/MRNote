"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet } from "@/lib/api";

export interface Hit {
  id?: string;
  asset_id?: string;
  chunk_id?: string | null;
  page_id?: string;
  memory_view_id?: string;
  notebook_id?: string;
  project_id?: string;
  title?: string;
  snippet?: string;
  score: number;
  source: string;
}

export interface SearchResults {
  pages: Hit[];
  blocks: Hit[];
  study_assets: Hit[];
  memory: Hit[];
  playbooks: Hit[];
}

export interface SearchResponse {
  query: string;
  duration_ms: number;
  results: SearchResults;
}

export function useSearch(notebookId?: string) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResults>({
    pages: [], blocks: [], study_assets: [], memory: [], playbooks: [],
  });
  const [loading, setLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const doSearch = useCallback(async (q: string) => {
    abortRef.current?.abort();
    if (q.trim().length < 2) {
      setResults({ pages: [], blocks: [], study_assets: [], memory: [], playbooks: [] });
      setLoading(false);
      return;
    }
    const ac = new AbortController();
    abortRef.current = ac;
    setLoading(true);
    try {
      const path = notebookId
        ? `/api/v1/notebooks/${notebookId}/search?q=${encodeURIComponent(q)}`
        : `/api/v1/search/global?q=${encodeURIComponent(q)}`;
      const data = await apiGet<SearchResponse>(path, { signal: ac.signal });
      if (!ac.signal.aborted) setResults(data.results);
    } catch {
      /* swallow */
    } finally {
      if (!ac.signal.aborted) setLoading(false);
    }
  }, [notebookId]);

  useEffect(() => {
    const h = setTimeout(() => { void doSearch(query); }, 300);
    return () => clearTimeout(h);
  }, [query, doSearch]);

  return { query, setQuery, results, loading };
}
