"use client";

import { useCallback, useState } from "react";
import { useParams } from "next/navigation";
import { Sparkles } from "lucide-react";
import NoteEditor from "@/components/console/editor/NoteEditor";
import AIPanel from "@/components/console/editor/AIPanel";
import MemoryLinksPanel from "@/components/console/editor/MemoryLinksPanel";

export default function PageEditorPage() {
  const params = useParams<{ notebookId: string; pageId: string }>();
  const [showAI, setShowAI] = useState(false);
  const [editorPlainText, setEditorPlainText] = useState("");

  const handleInsertToEditor = useCallback((text: string) => {
    // TODO: Integrate with TipTap editor instance to insert content
    // For now this is a placeholder
    console.log("Insert to editor:", text);
  }, []);

  return (
    <div className="note-editor-page-layout">
      {/* Main editor area */}
      <div className="note-editor-main">
        <NoteEditor
          notebookId={params.notebookId}
          pageId={params.pageId}
          onPlainTextChange={setEditorPlainText}
        />
      </div>

      {/* AI toggle button (fixed) */}
      {!showAI && (
        <button
          type="button"
          className="note-ai-toggle"
          onClick={() => setShowAI(true)}
          title="Open AI Assistant"
        >
          <Sparkles size={18} />
        </button>
      )}

      {/* Right AI Panel */}
      {showAI && (
        <div className="note-ai-sidebar">
          <AIPanel
            pageId={params.pageId}
            pageContext={editorPlainText}
            onInsertToEditor={handleInsertToEditor}
            onClose={() => setShowAI(false)}
          />
          <MemoryLinksPanel pageId={params.pageId} />
        </div>
      )}
    </div>
  );
}
