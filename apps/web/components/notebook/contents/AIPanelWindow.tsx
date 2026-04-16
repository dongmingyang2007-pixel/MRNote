"use client";

import { useState } from "react";
import AskTab from "./ai-panel-tabs/AskTab";
import SummaryTab from "./ai-panel-tabs/SummaryTab";
import MemoryTab from "./ai-panel-tabs/MemoryTab";
import TraceTab from "./ai-panel-tabs/TraceTab";

type TabKey = "ask" | "summary" | "memory" | "trace";

interface AIPanelWindowProps {
  notebookId: string;
  pageId: string;
}

const TABS: { key: TabKey; label: string }[] = [
  { key: "ask", label: "Ask" },
  { key: "summary", label: "Summary" },
  { key: "memory", label: "Memory" },
  { key: "trace", label: "Trace" },
];

export default function AIPanelWindow({
  notebookId,
  pageId,
}: AIPanelWindowProps) {
  const [tab, setTab] = useState<TabKey>("ask");

  return (
    <div className="ai-panel-window">
      <div className="ai-panel-window__tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            data-testid={`ai-panel-tab-${t.key}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="ai-panel-window__body">
        {tab === "ask" && (
          <AskTab notebookId={notebookId} pageId={pageId} />
        )}
        {tab === "summary" && <SummaryTab pageId={pageId} />}
        {tab === "memory" && <MemoryTab pageId={pageId} />}
        {tab === "trace" && <TraceTab pageId={pageId} />}
      </div>
    </div>
  );
}
