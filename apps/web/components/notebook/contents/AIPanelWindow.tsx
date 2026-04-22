"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import AskTab from "./ai-panel-tabs/AskTab";
import SummaryTab from "./ai-panel-tabs/SummaryTab";
import RelatedTab from "./ai-panel-tabs/RelatedTab";
import MemoryTab from "./ai-panel-tabs/MemoryTab";
import StudyTab from "./ai-panel-tabs/StudyTab";
import TraceTab from "./ai-panel-tabs/TraceTab";

type TabKey = "ask" | "summary" | "related" | "memory" | "study" | "trace";

interface AIPanelWindowProps {
  notebookId: string;
  pageId: string;
}

const TAB_KEYS: TabKey[] = ["ask", "summary", "related", "memory", "study", "trace"];

export default function AIPanelWindow({
  notebookId,
  pageId,
}: AIPanelWindowProps) {
  const t = useTranslations("console-notebooks");
  const [tab, setTab] = useState<TabKey>("ask");

  return (
    <div className="ai-panel-window">
      <div className="ai-panel-window__tabs" role="tablist">
        {TAB_KEYS.map((tabKey) => (
          <button
            key={tabKey}
            type="button"
            role="tab"
            aria-selected={tab === tabKey}
            data-testid={`ai-panel-tab-${tabKey}`}
            onClick={() => setTab(tabKey)}
          >
            {t(`aiPanel.tab.${tabKey}`)}
          </button>
        ))}
      </div>
      <div className="ai-panel-window__body">
        {tab === "ask" && (
          <AskTab notebookId={notebookId} pageId={pageId} />
        )}
        {tab === "summary" && <SummaryTab pageId={pageId} />}
        {tab === "related" && <RelatedTab pageId={pageId} />}
        {tab === "memory" && <MemoryTab pageId={pageId} />}
        {tab === "study" && <StudyTab notebookId={notebookId} />}
        {tab === "trace" && <TraceTab pageId={pageId} />}
      </div>
    </div>
  );
}
