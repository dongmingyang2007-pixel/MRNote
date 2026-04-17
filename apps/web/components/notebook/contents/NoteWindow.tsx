"use client";

import NoteEditor from "@/components/console/editor/NoteEditor";
import RelatedPagesCard from "./search/RelatedPagesCard";

interface NoteWindowProps {
  pageId: string;
}

export default function NoteWindow({ pageId }: NoteWindowProps) {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ maxWidth: "none", flex: 1, minHeight: 0, overflow: "auto" }}>
        <NoteEditor pageId={pageId} />
      </div>
      {pageId && <RelatedPagesCard pageId={pageId} />}
    </div>
  );
}
