"use client";

import AIActionsList from "@/components/notebook/AIActionsList";

interface TraceTabProps {
  pageId: string;
}

export default function TraceTab({ pageId }: TraceTabProps) {
  return <AIActionsList pageId={pageId} />;
}
