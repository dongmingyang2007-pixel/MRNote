"use client";

import { useCallback } from "react";
import { useLocale } from "next-intl";

import NoteEditor from "@/components/console/editor/NoteEditor";
import { requestGuestRegisterGate } from "@/components/console/GuestRegisterGate";
import { useWindowManager } from "@/components/notebook/WindowManager";

function initialContent(locale: string): Record<string, unknown> {
  const text =
    locale === "en"
      ? "Write directly in the real notebook workspace. Save, upload sources, use the assistant, or open the graph when you create an account."
      : "直接在真实 notebook 工作区里写。需要保存、上传资料、使用助手或打开图谱时，再创建账号。";

  return {
    type: "doc",
    content: [
      {
        type: "paragraph",
        content: [{ type: "text", text }],
      },
    ],
  };
}

export default function GuestLocalNoteWindow() {
  const locale = useLocale();
  const { renameWindowByMeta } = useWindowManager();
  const title = locale === "en" ? "Start with a page" : "今天先写一点";

  const handleTitleChange = useCallback(
    (nextTitle: string) => {
      renameWindowByMeta(
        "guestPageId",
        "guest-draft",
        nextTitle.trim() || title,
      );
    },
    [renameWindowByMeta, title],
  );

  return (
    <div style={{ height: "100%", overflow: "auto" }}>
      <NoteEditor
        pageId="guest-draft"
        guestMode
        initialTitle={title}
        initialContent={initialContent(locale)}
        onTitleChange={handleTitleChange}
        onGuestSaveRequest={() => requestGuestRegisterGate("save")}
      />
    </div>
  );
}
