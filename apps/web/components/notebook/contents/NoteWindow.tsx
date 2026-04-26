"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import NoteEditor from "@/components/console/editor/NoteEditor";
import RelatedPagesCard from "./search/RelatedPagesCard";
import ReferencingHighlights from "./ReferencingHighlights";
import { apiGet } from "@/lib/api";
import { useWindowManager } from "@/components/notebook/WindowManager";
import { dispatchNotebookPagesChanged } from "@/lib/notebook-events";

interface NoteWindowProps {
  pageId: string;
}

export default function NoteWindow({ pageId }: NoteWindowProps) {
  const { renameWindowByMeta } = useWindowManager();
  const t = useTranslations("console-notebooks");
  const refreshTimerRef = useRef<number | null>(null);
  const [notebookId, setNotebookId] = useState<string>("");

  useEffect(() => {
    return () => {
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
      }
    };
  }, []);

  // Look up the notebook id once so ReferencingHighlights can open the
  // matching reference document window.
  useEffect(() => {
    if (!pageId) return;
    let cancelled = false;
    void apiGet<{ notebook_id?: string }>(`/api/v1/pages/${pageId}`)
      .then((data) => {
        if (!cancelled && data.notebook_id) {
          setNotebookId(data.notebook_id);
        }
      })
      .catch(() => {
        /* silent — non-blocking */
      });
    return () => {
      cancelled = true;
    };
  }, [pageId]);

  // Keep window titlebar + minimized-tray label in sync with the editor title.
  const handleTitleChange = useCallback(
    (title: string) => {
      renameWindowByMeta("pageId", pageId, title.trim() || t("pages.untitled"));
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
      }
      refreshTimerRef.current = window.setTimeout(() => {
        // U-05 — notify listeners (e.g. NoteTitlebarExtras) that the page
        // changed so the titlebar metadata (updated_at) refreshes.
        // `dispatchNotebookPagesChanged` already fires the event under the
        // hood; the redundant `window.dispatchEvent(new CustomEvent(...))`
        // that lived here doubled every refresh and broke listeners that
        // tracked dispatch counts.
        dispatchNotebookPagesChanged();
      }, 250);
    },
    [pageId, renameWindowByMeta, t],
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ maxWidth: "none", flex: 1, minHeight: 0, overflow: "auto" }}>
        <NoteEditor pageId={pageId} onTitleChange={handleTitleChange} />
        {pageId && notebookId ? (
          <ReferencingHighlights pageId={pageId} notebookId={notebookId} />
        ) : null}
      </div>
      {pageId && <RelatedPagesCard pageId={pageId} />}
    </div>
  );
}
