"use client";

import { useCallback, useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import NoteEditor from "@/components/console/editor/NoteEditor";
import RelatedPagesCard from "./search/RelatedPagesCard";
import { useWindowManager } from "@/components/notebook/WindowManager";
import { NOTEBOOK_PAGES_CHANGED_EVENT } from "@/lib/notebook-events";

interface NoteWindowProps {
  pageId: string;
}

export default function NoteWindow({ pageId }: NoteWindowProps) {
  const { renameWindowByMeta } = useWindowManager();
  const t = useTranslations("console-notebooks");
  const refreshTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
      }
    };
  }, []);

  // Keep window titlebar + minimized-tray label in sync with the editor title.
  const handleTitleChange = useCallback(
    (title: string) => {
      renameWindowByMeta("pageId", pageId, title.trim() || t("pages.untitled"));
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
      }
      refreshTimerRef.current = window.setTimeout(() => {
        window.dispatchEvent(new CustomEvent(NOTEBOOK_PAGES_CHANGED_EVENT));
      }, 250);
    },
    [pageId, renameWindowByMeta, t],
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ maxWidth: "none", flex: 1, minHeight: 0, overflow: "auto" }}>
        <NoteEditor pageId={pageId} onTitleChange={handleTitleChange} />
      </div>
      {pageId && <RelatedPagesCard pageId={pageId} />}
    </div>
  );
}
