"use client";

import NoteEditor from "@/components/console/editor/NoteEditor";

interface NoteWindowProps {
  pageId: string;
}

export default function NoteWindow({ pageId }: NoteWindowProps) {
  return (
    <div style={{ maxWidth: "none", height: "100%", overflow: "auto" }}>
      <NoteEditor pageId={pageId} />
    </div>
  );
}
