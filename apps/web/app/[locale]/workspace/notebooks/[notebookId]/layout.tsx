"use client";

import "@/styles/ai-panel-window.css";
import "@/styles/study-window.css";
import "@/styles/digest-window.css";
import "@/styles/search-window.css";
import { useParams } from "next/navigation";
import NotebookSidebar from "@/components/console/NotebookSidebar";
import { WindowManagerProvider } from "@/components/notebook/WindowManager";

export default function NotebookWorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const params = useParams<{ notebookId: string }>();

  // `key={notebookId}` forces a fresh WindowManagerProvider (and a
  // fresh hydration via loadPersistedLayout) whenever the active
  // notebook changes — even if the layout instance survives a
  // client-side route swap. Without it, the persist effect would
  // overwrite the new notebook's storage with the old notebook's
  // windows on the next reducer tick.
  return (
    <WindowManagerProvider key={params.notebookId} notebookId={params.notebookId}>
      <div style={{ display: "flex", height: "calc(100vh - 48px - 28px)", marginLeft: -56 }}>
        {/* NotebookSidebar replaces the global sidebar */}
        <NotebookSidebar notebookId={params.notebookId} />

        {/* Content area */}
        <div style={{ flex: 1, overflow: "hidden", minWidth: 0, position: "relative" }}>
          {children}
        </div>
      </div>
    </WindowManagerProvider>
  );
}
