"use client";

import "@/styles/ai-panel-window.css";
import { useParams } from "next/navigation";
import NotebookSidebar from "@/components/console/NotebookSidebar";
import { WindowManagerProvider } from "@/components/notebook/WindowManager";

export default function NotebookWorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const params = useParams<{ notebookId: string }>();

  return (
    <WindowManagerProvider notebookId={params.notebookId}>
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
