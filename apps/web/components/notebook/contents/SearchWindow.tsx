"use client";

import { FileText, Layers, Brain, BookOpen, ScrollText } from "lucide-react";
import { useWindowManager } from "@/components/notebook/WindowManager";
import SearchResultsGroup from "./search/SearchResultsGroup";
import { useSearch, type Hit } from "@/hooks/useSearch";

interface Props {
  notebookId?: string;
  projectId?: string;
}

export default function SearchWindow({ notebookId }: Props) {
  const { query, setQuery, results, loading } = useSearch(notebookId);
  const { openWindow } = useWindowManager();

  const pickPage = (hit: Hit) => {
    if (!hit.id || !hit.notebook_id) return;
    openWindow({
      type: "note", title: hit.title || "Page",
      meta: { pageId: hit.id, notebookId: hit.notebook_id },
    });
  };
  const pickBlock = (hit: Hit) => {
    if (!hit.page_id || !hit.notebook_id) return;
    openWindow({
      type: "note", title: "Page",
      meta: { pageId: hit.page_id, notebookId: hit.notebook_id },
    });
  };
  const pickStudy = (hit: Hit) => {
    if (!hit.notebook_id) return;
    openWindow({
      type: "study", title: "Study",
      meta: { notebookId: hit.notebook_id },
    });
  };
  const pickMemory = (hit: Hit) => {
    if (!notebookId) return;
    openWindow({
      type: "memory", title: "Memory",
      meta: { notebookId, memoryId: hit.id || "" },
    });
  };
  const pickPlaybook = (hit: Hit) => {
    if (!notebookId) return;
    openWindow({
      type: "memory", title: "Playbook",
      meta: { notebookId, memoryViewId: hit.memory_view_id || "" },
    });
  };

  return (
    <div className="search-window" data-testid="search-window">
      <div className="search-window__header">
        <input
          type="text"
          placeholder="Search pages, blocks, memory, study…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          autoFocus
          data-testid="search-window-input"
        />
        {loading && <span className="search-window__loading">…</span>}
      </div>

      <div className="search-window__body">
        <SearchResultsGroup
          heading="Pages"
          icon={FileText}
          items={results.pages}
          onPick={pickPage}
        />
        <SearchResultsGroup
          heading="Blocks"
          icon={Layers}
          items={results.blocks}
          onPick={pickBlock}
        />
        <SearchResultsGroup
          heading="Study assets"
          icon={BookOpen}
          items={results.study_assets}
          onPick={pickStudy}
        />
        <SearchResultsGroup
          heading="Memory"
          icon={Brain}
          items={results.memory}
          onPick={pickMemory}
        />
        <SearchResultsGroup
          heading="Playbooks"
          icon={ScrollText}
          items={results.playbooks}
          onPick={pickPlaybook}
        />
      </div>
    </div>
  );
}
