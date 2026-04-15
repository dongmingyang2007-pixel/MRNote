"use client";

import { useCallback } from "react";
import AIPanel from "@/components/console/editor/AIPanel";

interface ChatWindowProps {
  notebookId: string;
  pageId?: string;
}

export default function ChatWindow({ notebookId, pageId }: ChatWindowProps) {
  // onClose is a no-op because the Window shell handles closing
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
