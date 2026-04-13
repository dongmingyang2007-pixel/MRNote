"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import NotebookSidebar from "@/components/console/NotebookSidebar";
import { apiGet } from "@/lib/api";

interface NotebookInfo {
  id: string;
  title: string;
  project_id: string | null;
}

export default function NotebookWorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const params = useParams<{ notebookId: string }>();
  const [notebook, setNotebook] = useState<NotebookInfo | null>(null);

  useEffect(() => {
    void apiGet<NotebookInfo>(`/api/v1/notebooks/${params.notebookId}`)
      .then(setNotebook)
      .catch(() => setNotebook(null));
  }, [params.notebookId]);

  return (
    <div style={{ display: "flex", height: "calc(100vh - 48px - 28px)", marginLeft: -56 }}>
      {/* NotebookSidebar replaces the global sidebar */}
      <NotebookSidebar
        notebookId={params.notebookId}
        notebookTitle={notebook?.title}
      />

      {/* Content area */}
      <div style={{ flex: 1, overflow: "auto", minWidth: 0 }}>
        {children}
      </div>
    </div>
  );
}
