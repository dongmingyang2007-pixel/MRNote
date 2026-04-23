"use client";

import { useCallback } from "react";
import AIPanel from "@/components/console/editor/AIPanel";

interface AskTabProps {
  notebookId: string;
  pageId: string;
}

export default function AskTab({ notebookId, pageId }: AskTabProps) {
  const noop = useCallback(() => {}, []);

  const handleInsertAIBlock = useCallback(
    (payload: {
      content_markdown: string;
      action_type: string;
      action_log_id: string;
      model_id: string | null;
      sources: Array<{ type: string; id: string; title: string }>;
    }) => {
      if (typeof window === "undefined") return;
      window.dispatchEvent(
        new CustomEvent("mrai:insert-ai-output", { detail: payload }),
      );
    },
    [],
  );

  return (
    <div style={{ height: "100%", overflow: "auto" }}>
      <AIPanel
        notebookId={notebookId}
        pageId={pageId}
        onInsertAIOutput={handleInsertAIBlock}
        onClose={noop}
        hideCloseButton
      />
    </div>
  );
}
