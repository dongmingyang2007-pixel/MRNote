"use client";

import { useCallback } from "react";
import AIPanel from "@/components/console/editor/AIPanel";

interface AskTabProps {
  notebookId: string;
  pageId: string;
}

export default function AskTab({ notebookId, pageId }: AskTabProps) {
  // The Window shell already handles close; onClose is a no-op here.
  const noop = useCallback(() => {}, []);

  return (
    <div style={{ height: "100%", overflow: "auto" }}>
      <AIPanel
        notebookId={notebookId}
        pageId={pageId}
        onClose={noop}
      />
    </div>
  );
}
