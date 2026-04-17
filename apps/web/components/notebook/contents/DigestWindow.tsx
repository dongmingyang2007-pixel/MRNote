"use client";

import { useState } from "react";
import DigestList from "./digest/DigestList";
import DigestDetail from "./digest/DigestDetail";

type DigestTab = "today" | "week" | "all";

interface Props {
  notebookId: string;
}

export default function DigestWindow({ notebookId }: Props) {
  const [tab, setTab] = useState<DigestTab>("today");
  const [activeDigestId, setActiveDigestId] = useState<string | null>(null);

  const filters =
    tab === "today" ? { kind: "daily_digest" as const } :
    tab === "week" ? { kind: "weekly_reflection" as const } :
    {};

  if (activeDigestId) {
    return (
      <div className="digest-window" data-testid="digest-window">
        <DigestDetail
          digestId={activeDigestId}
          notebookId={notebookId}
          onBack={() => setActiveDigestId(null)}
        />
      </div>
    );
  }

  return (
    <div className="digest-window" data-testid="digest-window">
      <div className="digest-window__tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "today"}
          data-testid="digest-tab-today"
          onClick={() => setTab("today")}
        >
          Today
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "week"}
          data-testid="digest-tab-week"
          onClick={() => setTab("week")}
        >
          This week
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "all"}
          data-testid="digest-tab-all"
          onClick={() => setTab("all")}
        >
          All
        </button>
      </div>
      <div className="digest-window__body">
        <DigestList
          kind={filters.kind}
          onPick={(d) => setActiveDigestId(d.id)}
        />
      </div>
    </div>
  );
}
