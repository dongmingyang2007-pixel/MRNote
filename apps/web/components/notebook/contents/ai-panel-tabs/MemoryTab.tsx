"use client";

import MemoryLinksPanel from "@/components/console/editor/MemoryLinksPanel";

interface MemoryTabProps {
  pageId: string;
}

export default function MemoryTab({ pageId }: MemoryTabProps) {
  return <MemoryLinksPanel pageId={pageId} embedded />;
}
