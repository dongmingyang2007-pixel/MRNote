"use client";

import { useCallback } from "react";
import { useTranslations } from "next-intl";
import NoteEditor from "@/components/console/editor/NoteEditor";
import RelatedPagesCard from "./search/RelatedPagesCard";
import { useWindowManager } from "@/components/notebook/WindowManager";

interface NoteWindowProps {
  pageId: string;
}

export default function NoteWindow({ pageId }: NoteWindowProps) {
  const { renameWindowByMeta } = useWindowManager();
  const t = useTranslations("console-notebooks");

  // Keep window titlebar + minimized-tray label in sync with the editor title.
  const handleTitleChange = useCallback(
    (title: string) => {
      renameWindowByMeta("pageId", pageId, title.trim() || t("pages.untitled"));
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
