"use client";

import { BookOpen, Bot, Brain, FileText, Layers, Paperclip, ScrollText } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { useWindowManager } from "@/components/notebook/WindowManager";
import { apiGet } from "@/lib/api";
import SearchResultsGroup from "./search/SearchResultsGroup";
import { useSearch, type Hit } from "@/hooks/useSearch";

interface Props {
  notebookId?: string;
  projectId?: string;
}

interface DataItemResponse {
  filename: string;
  media_type: string;
  preview_url?: string | null;
  download_url?: string | null;
}

export default function SearchWindow({ notebookId }: Props) {
  const t = useTranslations("console-notebooks");
  const router = useRouter();
  const { query, setQuery, results, loading } = useSearch(notebookId);
  const { openWindow } = useWindowManager();

  const openFileWindow = (options: {
    title: string;
    filename: string;
    mimeType?: string;
    previewUrl?: string | null;
    downloadUrl?: string | null;
  }) => {
    const previewUrl = options.previewUrl?.trim() || "";
    const downloadUrl = options.downloadUrl?.trim() || previewUrl;
    if (!previewUrl && !downloadUrl) {
      return;
    }
    openWindow({
      type: "file",
      title: options.title,
      meta: {
        previewUrl,
        downloadUrl,
        mimeType: options.mimeType || "",
        filename: options.filename,
      },
    });
  };

  const pickPage = (hit: Hit) => {
    if (!hit.id || !hit.notebook_id) return;
    openWindow({
      type: "note", title: hit.title || t("search.window.openPage"),
      meta: { pageId: hit.id, notebookId: hit.notebook_id },
    });
  };
  const pickBlock = (hit: Hit) => {
    if (!hit.page_id || !hit.notebook_id) return;
    openWindow({
      type: "note", title: t("search.window.openPage"),
      meta: { pageId: hit.page_id, notebookId: hit.notebook_id },
    });
  };
  const pickStudy = (hit: Hit) => {
    if (!hit.notebook_id) return;
    openWindow({
      type: "study", title: t("search.window.openStudy"),
      meta: { notebookId: hit.notebook_id, assetId: hit.asset_id || hit.id || "" },
    });
  };
  const pickFile = async (hit: Hit) => {
    if (hit.attachment_id) {
      try {
        const data = await apiGet<{ url: string }>(
          `/api/v1/attachments/${hit.attachment_id}/url`,
        );
        const filename = hit.title || t("search.window.openFile");
        const mimeType = hit.mime_type || "";
        openFileWindow({
          title: filename,
          filename,
          mimeType,
          previewUrl: mimeType.startsWith("image/") ? data.url : null,
          downloadUrl: data.url,
        });
      } catch {
        /* ignore */
      }
      return;
    }
    if (!hit.data_item_id) return;
    try {
      const data = await apiGet<DataItemResponse>(
        `/api/v1/data-items/${hit.data_item_id}`,
      );
      const filename = data.filename || hit.title || t("search.window.openFile");
      openFileWindow({
        title: filename,
        filename,
        mimeType: data.media_type || hit.mime_type || "",
        previewUrl: data.preview_url || null,
        downloadUrl: data.download_url || data.preview_url || null,
      });
    } catch {
      /* ignore */
    }
  };
  const pickMemory = (hit: Hit) => {
    const targetNotebookId = hit.notebook_id || notebookId;
    if (!targetNotebookId) return;
    openWindow({
      type: "memory_graph", title: t("search.window.openMemory"),
      meta: { notebookId: targetNotebookId, memoryId: hit.id || "" },
    });
  };
  const pickPlaybook = (hit: Hit) => {
    const targetNotebookId = hit.notebook_id || notebookId;
    if (!targetNotebookId) return;
    openWindow({
      type: "memory_graph", title: t("search.window.openPlaybook"),
      meta: { notebookId: targetNotebookId, memoryViewId: hit.memory_view_id || "" },
    });
  };
  const pickAiAction = (hit: Hit) => {
    if (hit.notebook_id && hit.page_id) {
      openWindow({
        type: "note",
        title: hit.title || t("search.window.openPage"),
        meta: { notebookId: hit.notebook_id, pageId: hit.page_id },
      });
      return;
    }
    if (hit.notebook_id) {
      router.push(`/app/notebooks/${hit.notebook_id}`);
    }
  };

  return (
    <div className="search-window" data-testid="search-window">
      <div className="search-window__header">
        <input
          type="text"
          placeholder={t("search.window.placeholder")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          autoFocus
          data-testid="search-window-input"
        />
        {loading && <span className="search-window__loading">…</span>}
      </div>

      <div className="search-window__body">
        <SearchResultsGroup
          heading={t("search.window.groupPages")}
          icon={FileText}
          items={results.pages}
          onPick={pickPage}
        />
        <SearchResultsGroup
          heading={t("search.window.groupBlocks")}
          icon={Layers}
          items={results.blocks}
          onPick={pickBlock}
        />
        <SearchResultsGroup
          heading={t("search.window.groupStudy")}
          icon={BookOpen}
          items={results.study_assets}
          onPick={pickStudy}
        />
        <SearchResultsGroup
          heading={t("search.window.groupFiles")}
          icon={Paperclip}
          items={results.files}
          onPick={(hit) => { void pickFile(hit); }}
        />
        <SearchResultsGroup
          heading={t("search.window.groupMemory")}
          icon={Brain}
          items={results.memory}
          onPick={pickMemory}
        />
        <SearchResultsGroup
          heading={t("search.window.groupPlaybooks")}
          icon={ScrollText}
          items={results.playbooks}
          onPick={pickPlaybook}
        />
        <SearchResultsGroup
          heading={t("search.window.groupAiActions")}
          icon={Bot}
          items={results.ai_actions}
          onPick={pickAiAction}
        />
      </div>
    </div>
  );
}
