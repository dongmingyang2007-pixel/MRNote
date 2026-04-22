"use client";

import { useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { useParams, useSearchParams } from "next/navigation";
import { useRouter } from "@/i18n/navigation";
import { useWindowManager } from "@/components/notebook/WindowManager";
import WindowCanvas from "@/components/notebook/WindowCanvas";

export default function NotebookDetailPage() {
  const params = useParams<{ notebookId: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const t = useTranslations("console-notebooks");
  const { openWindow } = useWindowManager();
  const handledOpenTargetRef = useRef("");

  useEffect(() => {
    const openPageId = searchParams.get("openPage");
    const openTarget = openPageId ? `${params.notebookId}:${openPageId}` : "";
    if (!openPageId || handledOpenTargetRef.current === openTarget) {
      return;
    }

    openWindow({
      type: "note",
      title: t("pages.untitled"),
      meta: { notebookId: params.notebookId, pageId: openPageId },
    });
    handledOpenTargetRef.current = openTarget;
    router.replace(`/app/notebooks/${params.notebookId}`);
  }, [openWindow, params.notebookId, router, searchParams, t]);

  return (
    <div style={{ width: "100%", height: "100%", minWidth: 0, minHeight: 0 }}>
      <WindowCanvas />
    </div>
  );
}
