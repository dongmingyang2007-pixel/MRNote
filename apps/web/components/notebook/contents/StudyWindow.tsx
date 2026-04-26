"use client";

import {
  type ChangeEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import type { LucideIcon } from "lucide-react";
import {
  Activity,
  BookOpen,
  Brain,
  FileText,
  Loader2,
  MessagesSquare,
  Network,
  ScrollText,
  Sparkles,
  Upload,
} from "lucide-react";
import { useTranslations } from "next-intl";
import DecksPanel from "./study/DecksPanel";
import ReviewSession from "./study/ReviewSession";
import StudyProgressPanel from "./study/StudyProgressPanel";
import ReferenceDocumentWindow from "./ReferenceDocumentWindow";
import { apiGet } from "@/lib/api";
import { apiStream } from "@/lib/api-stream";
import { STUDY_UPLOAD_ACCEPT, uploadStudyAssets } from "@/lib/study-upload";
import { useWindowManager } from "@/components/notebook/WindowManager";
import { NOTEBOOK_STUDY_CHANGED_EVENT } from "@/lib/notebook-events";

type StudyTab =
  | "overview"
  | "document"
  | "progress"
  | "assistant"
  | "decks"
  | "review";

interface StudyWindowProps {
  notebookId: string;
  initialAssetId?: string;
}

interface StudyAssetMetadata {
  overview_page_id?: string;
  notes_page_id?: string;
  chapter_page_ids?: string[];
}

interface StudyAsset {
  id: string;
  notebook_id: string;
  data_item_id?: string | null;
  title: string;
  asset_type: string;
  status: string;
  total_chunks: number;
  created_at: string;
  updated_at: string;
  metadata_json?: StudyAssetMetadata | null;
}

interface StudyChunk {
  id: string;
  chunk_index: number;
  heading: string;
  content: string;
  page_number: number | null;
}

interface NotebookPageListItem {
  id: string;
  title: string;
  slug: string;
}

interface StudySource {
  heading?: string;
  page_number?: number | null;
  chunk_id?: string | null;
  asset_id?: string;
  asset_title?: string;
  data_item_id?: string | null;
  type?: string;
  score?: number;
}

type AssistantScope = "asset" | "notebook";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  sources?: StudySource[];
}

const TABS: Array<{
  id: StudyTab;
  icon: LucideIcon;
  labelKey: string;
  testId: string;
}> = [
  { id: "overview", icon: BookOpen, labelKey: "study.workspace.tabs.overview", testId: "study-tab-overview" },
  { id: "document", icon: FileText, labelKey: "study.workspace.tabs.document", testId: "study-tab-document" },
  { id: "progress", icon: Activity, labelKey: "study.workspace.tabs.progress", testId: "study-tab-progress" },
  { id: "assistant", icon: MessagesSquare, labelKey: "study.workspace.tabs.assistant", testId: "study-tab-assistant" },
  { id: "decks", icon: Sparkles, labelKey: "study.workspace.tabs.decks", testId: "study-tab-decks" },
  { id: "review", icon: Brain, labelKey: "study.workspace.tabs.review", testId: "study-tab-review" },
];

const surfaceStyle: CSSProperties = {
  border: "1px solid rgba(15, 23, 42, 0.08)",
  borderRadius: 18,
  background: "rgba(255,255,255,0.86)",
};

export default function StudyWindow({
  notebookId,
  initialAssetId,
}: StudyWindowProps) {
  const t = useTranslations("console-notebooks");
  const { openWindow } = useWindowManager();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const assistantAbortRef = useRef<AbortController | null>(null);

  const [tab, setTab] = useState<StudyTab>("overview");
  const [reviewingDeckId, setReviewingDeckId] = useState<string | null>(null);
  const [assets, setAssets] = useState<StudyAsset[]>([]);
  const [loadingAssets, setLoadingAssets] = useState(true);
  const [selectedAssetId, setSelectedAssetId] = useState<string | null>(
    initialAssetId ?? null,
  );
  const [notebookPages, setNotebookPages] = useState<NotebookPageListItem[]>([]);
  const [chunks, setChunks] = useState<StudyChunk[]>([]);
  const [loadingChunks, setLoadingChunks] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{
    done: number;
    total: number;
  } | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [assistantMessages, setAssistantMessages] = useState<ChatMessage[]>([]);
  const [assistantInput, setAssistantInput] = useState("");
  const [assistantError, setAssistantError] = useState<string | null>(null);
  const [assistantStreaming, setAssistantStreaming] = useState(false);
  const [streamingReply, setStreamingReply] = useState("");
  const [streamingSources, setStreamingSources] = useState<StudySource[]>([]);
  const [assistantScope, setAssistantScope] = useState<AssistantScope>("asset");

  const selectedAsset =
    assets.find((asset) => asset.id === selectedAssetId) || null;

  const statusLabel = (status: string): string => {
    const map: Record<string, string> = {
      pending: t("study.assets.statusPending"),
      parsing: t("study.assets.statusParsing"),
      chunked: t("study.assets.statusChunked"),
      indexed: t("study.assets.statusIndexed"),
      failed: t("study.assets.statusFailed"),
    };
    return map[status] ?? status;
  };

  const generatedPages = (() => {
    if (!selectedAsset) {
      return [];
    }
    const metadata = selectedAsset.metadata_json || {};
    const items: Array<{
      id: string;
      label: string;
      icon: LucideIcon;
      kind: "overview" | "notes" | "chapter" | "page";
    }> = [];

    if (metadata.overview_page_id) {
      items.push({
        id: metadata.overview_page_id,
        label: t("study.workspace.pages.overview"),
        icon: FileText,
        kind: "overview",
      });
    }
    if (metadata.notes_page_id) {
      items.push({
        id: metadata.notes_page_id,
        label: t("study.workspace.pages.notes"),
        icon: ScrollText,
        kind: "notes",
      });
    }
    const chapterPageIds = Array.isArray(metadata.chapter_page_ids)
      ? metadata.chapter_page_ids
      : [];
    chapterPageIds.forEach((pageId, index) => {
      items.push({
        id: pageId,
        label: t("study.workspace.pages.chapter", { index: index + 1 }),
        icon: BookOpen,
        kind: "chapter",
      });
    });

    if (items.length > 0) {
      return items;
    }

    const slugPrefix = `study-asset-${selectedAsset.id}-`;
    const derived = notebookPages
      .filter((page) => page.slug.startsWith(slugPrefix))
      .sort((a, b) => {
        const rank = (slug: string): number => {
          if (slug.endsWith("-overview")) return 0;
          if (slug.endsWith("-notes")) return 1;
          const chapterMatch = slug.match(/-chapter-(\d+)$/);
          if (chapterMatch) return 10 + Number(chapterMatch[1]);
          return 999;
        };
        return rank(a.slug) - rank(b.slug);
      })
      .map((page) => {
        if (page.slug.endsWith("-overview")) {
          return { id: page.id, label: t("study.workspace.pages.overview"), icon: FileText, kind: "overview" as const };
        }
        if (page.slug.endsWith("-notes")) {
          return { id: page.id, label: t("study.workspace.pages.notes"), icon: ScrollText, kind: "notes" as const };
        }
        const chapterMatch = page.slug.match(/-chapter-(\d+)$/);
        if (chapterMatch) {
          return {
            id: page.id,
            label: t("study.workspace.pages.chapter", { index: Number(chapterMatch[1]) }),
            icon: BookOpen,
            kind: "chapter" as const,
          };
        }
        return { id: page.id, label: page.title, icon: FileText, kind: "page" as const };
      });
    return derived;
  })();

  const loadAssets = useCallback(async () => {
    setLoadingAssets(true);
    try {
      const data = await apiGet<{ items: StudyAsset[] }>(
        `/api/v1/notebooks/${notebookId}/study-assets`,
      );
      setAssets(data.items || []);
    } catch {
      setAssets([]);
    } finally {
      setLoadingAssets(false);
    }
  }, [notebookId]);

  const loadNotebookPages = useCallback(async () => {
    try {
      const data = await apiGet<{ items: NotebookPageListItem[] }>(
        `/api/v1/notebooks/${notebookId}/pages`,
      );
      setNotebookPages(data.items || []);
    } catch {
      setNotebookPages([]);
    }
  }, [notebookId]);

  const loadChunks = useCallback(async (assetId: string) => {
    setLoadingChunks(true);
    try {
      const data = await apiGet<{ items: StudyChunk[] }>(
        `/api/v1/study-assets/${assetId}/chunks?limit=80`,
      );
      setChunks(data.items || []);
    } catch {
      setChunks([]);
    } finally {
      setLoadingChunks(false);
    }
  }, []);

  useEffect(() => {
    void loadAssets();
  }, [loadAssets]);

  useEffect(() => {
    void loadNotebookPages();
  }, [loadNotebookPages]);

  useEffect(() => {
    const handleStudyChanged = (event: Event) => {
      const detail = (
        event as CustomEvent<{ notebookId?: string }>
      ).detail;
      if (!detail?.notebookId || detail.notebookId === notebookId) {
        void loadAssets();
        void loadNotebookPages();
      }
    };
    window.addEventListener(NOTEBOOK_STUDY_CHANGED_EVENT, handleStudyChanged);
    return () => {
      window.removeEventListener(
        NOTEBOOK_STUDY_CHANGED_EVENT,
        handleStudyChanged,
      );
    };
  }, [loadAssets, notebookId]);

  useEffect(() => {
    if (!assets.some((asset) => asset.status === "indexed")) {
      return;
    }
    void loadNotebookPages();
  }, [assets, loadNotebookPages]);

  useEffect(() => {
    if (assets.length === 0) {
      setSelectedAssetId(null);
      return;
    }
    if (selectedAssetId && assets.some((asset) => asset.id === selectedAssetId)) {
      return;
    }
    if (initialAssetId && assets.some((asset) => asset.id === initialAssetId)) {
      setSelectedAssetId(initialAssetId);
      return;
    }
    setSelectedAssetId(assets[0].id);
  }, [assets, initialAssetId, selectedAssetId]);

  useEffect(() => {
    if (!selectedAsset || selectedAsset.status !== "indexed") {
      setChunks([]);
      return;
    }
    void loadChunks(selectedAsset.id);
  }, [loadChunks, selectedAsset?.id, selectedAsset?.status]);

  // Reset chat when the assistant scope changes, or when the selected
  // asset changes WHILE in asset scope. In notebook scope a source-pill
  // jump swaps `selectedAssetId` so the document tab loads the right
  // file, but the conversation context is still about the whole notebook
  // — so we leave the messages alone.
  useEffect(() => {
    assistantAbortRef.current?.abort();
    setAssistantMessages([]);
    setAssistantError(null);
    setAssistantStreaming(false);
    setStreamingReply("");
    setStreamingSources([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assistantScope, assistantScope === "asset" ? selectedAssetId : ""]);

  useEffect(() => {
    if (!assets.some((asset) => !["indexed", "failed", "deleted"].includes(asset.status))) {
      return;
    }
    const intervalId = window.setInterval(() => {
      void loadAssets();
    }, 4000);
    return () => window.clearInterval(intervalId);
  }, [assets, loadAssets]);

  useEffect(() => {
    return () => {
      assistantAbortRef.current?.abort();
    };
  }, []);

  const handleStartReview = (deckId: string) => {
    setReviewingDeckId(deckId);
    setTab("review");
  };

  const handleOpenUpload = () => {
    setUploadError(null);
    fileInputRef.current?.click();
  };

  const handleFilesSelected = async (
    event: ChangeEvent<HTMLInputElement>,
  ) => {
    const files = event.target.files ? Array.from(event.target.files) : [];
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
    if (files.length === 0) {
      return;
    }

    setUploading(true);
    setUploadError(null);
    setUploadProgress({ done: 0, total: files.length });
    try {
      const created = await uploadStudyAssets(notebookId, files, (done, total) =>
        setUploadProgress({ done, total }),
      );
      await loadAssets();
      if (created[0]?.id) {
        setSelectedAssetId(created[0].id);
      }
    } catch (error) {
      setUploadError(
        error instanceof Error ? error.message : t("study.workspace.uploadFailed"),
      );
    } finally {
      setUploading(false);
      setUploadProgress(null);
    }
  };

  const openNotebookPage = (pageId: string, title: string) => {
    openWindow({
      type: "note",
      title,
      meta: { notebookId, pageId },
    });
  };

  const handleOpenMemoryGraph = () => {
    openWindow({
      type: "memory_graph",
      title: t("memoryGraph.title"),
      meta: { notebookId },
    });
  };

  const handleAssistantPrompt = async (prompt: string) => {
    if (assistantStreaming) return;
    if (assistantScope === "asset" && !selectedAsset) return;

    assistantAbortRef.current?.abort();
    const ac = new AbortController();
    assistantAbortRef.current = ac;

    setAssistantError(null);
    setAssistantStreaming(true);
    setStreamingReply("");
    setStreamingSources([]);

    const history = assistantMessages.map((message) => ({
      role: message.role,
      content: message.content,
    }));
    const userMessage: ChatMessage = { role: "user", content: prompt };
    setAssistantMessages((prev) => [...prev, userMessage]);

    const requestBody =
      assistantScope === "notebook"
        ? {
            scope: "notebook",
            notebook_id: notebookId,
            message: prompt,
            history,
          }
        : {
            asset_id: selectedAsset?.id,
            message: prompt,
            history,
          };

    try {
      for await (const event of apiStream(
        "/api/v1/ai/study/ask",
        requestBody,
        ac.signal,
      )) {
        if (event.event === "message_start") {
          setStreamingSources(
            Array.isArray(event.data.sources)
              ? (event.data.sources as StudySource[])
              : [],
          );
          continue;
        }
        if (event.event === "token") {
          setStreamingReply(
            typeof event.data.snapshot === "string"
              ? event.data.snapshot
              : typeof event.data.content === "string"
                ? event.data.content
                : "",
          );
          continue;
        }
        if (event.event === "message_done") {
          const content =
            typeof event.data.content === "string"
              ? event.data.content
              : streamingReply;
          const sources = Array.isArray(event.data.sources)
            ? (event.data.sources as StudySource[])
            : streamingSources;
          setAssistantMessages((prev) => [
            ...prev,
            { role: "assistant", content, sources },
          ]);
          setStreamingReply("");
          setStreamingSources([]);
        }
        if (event.event === "error") {
          setAssistantError(
            typeof event.data.message === "string"
              ? event.data.message
              : t("study.workspace.assistantError"),
          );
        }
      }
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setAssistantError(
          error instanceof Error ? error.message : t("study.workspace.assistantError"),
        );
      }
    } finally {
      setAssistantStreaming(false);
      assistantAbortRef.current = null;
    }
  };

  const handleAssistantSubmit = async () => {
    const prompt = assistantInput.trim();
    if (!prompt) {
      return;
    }
    setAssistantInput("");
    await handleAssistantPrompt(prompt);
  };

  const renderAssetList = () => (
    <div style={{ ...surfaceStyle, padding: 18, display: "flex", flexDirection: "column", minHeight: 0 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          marginBottom: 16,
        }}
      >
        <div>
          <div style={{ fontSize: "0.75rem", fontWeight: 700, color: "var(--console-accent, var(--console-accent, #0D9488))", letterSpacing: "0.04em", textTransform: "uppercase" }}>
            {t("study.workspace.kicker")}
          </div>
          <h3 style={{ margin: "6px 0 0", fontSize: "1rem", color: "var(--console-text-primary, #0f172a)" }}>
            {t("study.workspace.libraryTitle")}
          </h3>
        </div>
        <button
          type="button"
          onClick={handleOpenUpload}
          disabled={uploading}
          data-testid="study-upload-button"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "8px 12px",
            borderRadius: 999,
            border: "none",
            background: "var(--console-cta-gradient, linear-gradient(135deg, #F97316, #EA6A0F))",
            color: "#fff",
            cursor: uploading ? "default" : "pointer",
            opacity: uploading ? 0.7 : 1,
          }}
        >
          {uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
          {uploading && uploadProgress
            ? t("study.assets.uploading", uploadProgress)
            : t("study.assets.upload")}
        </button>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept={STUDY_UPLOAD_ACCEPT}
        onChange={handleFilesSelected}
        style={{ display: "none" }}
        data-testid="study-upload-input"
      />

      {uploadError ? (
        <div
          role="alert"
          style={{
            padding: "8px 10px",
            marginBottom: 12,
            borderRadius: 12,
            background: "rgba(220, 38, 38, 0.08)",
            color: "#b91c1c",
            fontSize: "0.75rem",
          }}
        >
          {uploadError}
        </div>
      ) : null}

      <div style={{ display: "grid", gap: 10, minHeight: 0, overflowY: "auto" }}>
        {loadingAssets ? (
          <div style={{ display: "flex", justifyContent: "center", padding: 32 }}>
            <Loader2 size={20} className="animate-spin" style={{ color: "var(--console-text-muted, #64748b)" }} />
          </div>
        ) : assets.length === 0 ? (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: 12,
              minHeight: 240,
              color: "var(--console-text-muted, #64748b)",
              textAlign: "center",
            }}
          >
            <BookOpen size={34} strokeWidth={1.2} />
            <div style={{ fontSize: "0.875rem", fontWeight: 600 }}>
              {t("study.assets.empty")}
            </div>
            <div style={{ fontSize: "0.75rem", maxWidth: 280, lineHeight: 1.6 }}>
              {t("study.workspace.emptyBody")}
            </div>
          </div>
        ) : (
          assets.map((asset) => (
            <button
              key={asset.id}
              type="button"
              onClick={() => setSelectedAssetId(asset.id)}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: 12,
                padding: "14px 16px",
                borderRadius: 16,
                border: selectedAssetId === asset.id
                  ? "1px solid rgba(13, 148, 136, 0.28)"
                  : "1px solid rgba(15, 23, 42, 0.08)",
                background: selectedAssetId === asset.id
                  ? "rgba(239, 246, 255, 0.96)"
                  : "rgba(248, 250, 252, 0.88)",
                cursor: "pointer",
                textAlign: "left",
                width: "100%",
              }}
            >
              <div
                style={{
                  width: 34,
                  height: 34,
                  borderRadius: 12,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  background: "rgba(15, 23, 42, 0.06)",
                  color: "var(--console-text-primary, #0f172a)",
                  flexShrink: 0,
                }}
              >
                <FileText size={16} />
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: "0.875rem", fontWeight: 700, color: "var(--console-text-primary, #0f172a)" }}>
                  {asset.title || t("study.assets.untitled")}
                </div>
                <div style={{ marginTop: 5, fontSize: "0.75rem", color: "var(--console-text-muted, #64748b)" }}>
                  {asset.asset_type} · {t("study.assets.chunks", { count: asset.total_chunks })}
                </div>
                <div style={{ marginTop: 8, display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 8px", borderRadius: 999, background: "rgba(15, 23, 42, 0.06)", fontSize: "0.6875rem", color: "var(--console-text-muted, #64748b)" }}>
                  {asset.status === "indexed" || asset.status === "failed" ? null : (
                    <Loader2 size={11} className="animate-spin" />
                  )}
                  {statusLabel(asset.status)}
                </div>
              </div>
            </button>
          ))
        )}
      </div>
    </div>
  );

  const renderOverview = () => (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(280px, 0.9fr) minmax(0, 1.5fr)",
        gap: 18,
        height: "100%",
        minHeight: 0,
      }}
    >
      {renderAssetList()}

      <div style={{ display: "grid", gap: 18, minHeight: 0, overflowY: "auto" }}>
        <div style={{ ...surfaceStyle, padding: 20 }}>
          {selectedAsset ? (
            <>
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  justifyContent: "space-between",
                  gap: 16,
                }}
              >
                <div>
                  <div style={{ fontSize: "0.75rem", fontWeight: 700, color: "var(--console-accent, var(--console-accent, #0D9488))", letterSpacing: "0.04em", textTransform: "uppercase" }}>
                    {t("study.workspace.assetLabel")}
                  </div>
                  <h2 style={{ margin: "8px 0 0", fontSize: "1.35rem", color: "var(--console-text-primary, #0f172a)" }}>
                    {selectedAsset.title || t("study.assets.untitled")}
                  </h2>
                  <p style={{ margin: "10px 0 0", fontSize: "0.8125rem", color: "var(--console-text-muted, #64748b)", lineHeight: 1.7, maxWidth: 700 }}>
                    {t("study.workspace.assetSummary", {
                      status: statusLabel(selectedAsset.status),
                      chunks: selectedAsset.total_chunks,
                    })}
                  </p>
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  <button
                    type="button"
                    onClick={() => setTab("document")}
                    disabled={!selectedAsset.data_item_id}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                      padding: "8px 12px",
                      borderRadius: 999,
                      border: "1px solid rgba(15, 23, 42, 0.08)",
                      background: "#fff",
                      cursor: selectedAsset.data_item_id ? "pointer" : "default",
                      opacity: selectedAsset.data_item_id ? 1 : 0.55,
                    }}
                  >
                    <FileText size={14} />
                    {t("study.workspace.openDocument")}
                  </button>
                  <button
                    type="button"
                    onClick={() => setTab("assistant")}
                    disabled={selectedAsset.status !== "indexed"}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                      padding: "8px 12px",
                      borderRadius: 999,
                      border: "1px solid rgba(15, 23, 42, 0.08)",
                      background: "#fff",
                      cursor: selectedAsset.status === "indexed" ? "pointer" : "default",
                      opacity: selectedAsset.status === "indexed" ? 1 : 0.55,
                    }}
                  >
                    <MessagesSquare size={14} />
                    {t("study.workspace.openAssistant")}
                  </button>
                  <button
                    type="button"
                    onClick={() => setTab("decks")}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                      padding: "8px 12px",
                      borderRadius: 999,
                      border: "1px solid rgba(15, 23, 42, 0.08)",
                      background: "#fff",
                      cursor: "pointer",
                    }}
                  >
                    <Sparkles size={14} />
                    {t("study.workspace.openDecks")}
                  </button>
                  <button
                    type="button"
                    onClick={handleOpenMemoryGraph}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                      padding: "8px 12px",
                      borderRadius: 999,
                      border: "1px solid rgba(15, 23, 42, 0.08)",
                      background: "#fff",
                      cursor: "pointer",
                    }}
                  >
                    <Network size={14} />
                    {t("study.workspace.openMemory")}
                  </button>
                </div>
              </div>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
                  gap: 12,
                  marginTop: 18,
                }}
              >
                {[
                  { key: "generatedPages", value: generatedPages.length, label: t("study.workspace.generatedPages") },
                  { key: "chunks", value: selectedAsset.total_chunks, label: t("study.workspace.chunkCount") },
                  { key: "status", value: statusLabel(selectedAsset.status), label: t("study.workspace.ingestStatus") },
                ].map((item) => (
                  <div
                    key={item.key}
                    style={{
                      borderRadius: 16,
                      padding: "14px 16px",
                      background: "rgba(248, 250, 252, 0.88)",
                      border: "1px solid rgba(15, 23, 42, 0.08)",
                    }}
                  >
                    <div style={{ fontSize: "0.6875rem", textTransform: "uppercase", letterSpacing: "0.04em", color: "var(--console-text-muted, #64748b)" }}>
                      {item.label}
                    </div>
                    <div style={{ marginTop: 8, fontSize: "1.05rem", fontWeight: 700, color: "var(--console-text-primary, #0f172a)" }}>
                      {item.value}
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div style={{ minHeight: 180, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--console-text-muted, #64748b)" }}>
              {t("study.workspace.pickAsset")}
            </div>
          )}
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(240px, 0.85fr) minmax(0, 1.15fr)",
            gap: 18,
          }}
        >
          <div style={{ ...surfaceStyle, padding: 18 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
              <ScrollText size={16} />
              <strong>{t("study.workspace.generatedTitle")}</strong>
            </div>
            {generatedPages.length === 0 ? (
              <div style={{ fontSize: "0.8125rem", color: "var(--console-text-muted, #64748b)", lineHeight: 1.6 }}>
                {selectedAsset
                  ? t("study.workspace.generatedEmpty")
                  : t("study.workspace.pickAsset")}
              </div>
            ) : (
              <div style={{ display: "grid", gap: 8 }}>
                {generatedPages.map((page) => (
                  <button
                    key={page.id}
                    type="button"
                    onClick={() => openNotebookPage(page.id, page.label)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      padding: "10px 12px",
                      borderRadius: 14,
                      border: "1px solid rgba(15, 23, 42, 0.08)",
                      background: "rgba(248, 250, 252, 0.9)",
                      cursor: "pointer",
                      textAlign: "left",
                    }}
                  >
                    <page.icon size={14} />
                    <span>{page.label}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div style={{ ...surfaceStyle, padding: 18, minHeight: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
              <BookOpen size={16} />
              <strong>{t("study.workspace.chunkBrowser")}</strong>
            </div>
            {loadingChunks ? (
              <div style={{ display: "flex", justifyContent: "center", padding: 24 }}>
                <Loader2 size={18} className="animate-spin" />
              </div>
            ) : chunks.length === 0 ? (
              <div style={{ fontSize: "0.8125rem", color: "var(--console-text-muted, #64748b)", lineHeight: 1.6 }}>
                {selectedAsset?.status === "indexed"
                  ? t("study.assets.noChunks")
                  : t("study.workspace.chunksPending")}
              </div>
            ) : (
              <div style={{ display: "grid", gap: 10, maxHeight: 360, overflowY: "auto" }}>
                {chunks.slice(0, 8).map((chunk) => (
                  <div
                    key={chunk.id}
                    style={{
                      padding: "12px 14px",
                      borderRadius: 14,
                      border: "1px solid rgba(15, 23, 42, 0.08)",
                      background: "rgba(255,255,255,0.92)",
                    }}
                  >
                    <div style={{ fontSize: "0.75rem", fontWeight: 700, color: "var(--console-text-primary, #0f172a)" }}>
                      {chunk.heading || t("study.workspace.chunkLabel", { index: chunk.chunk_index + 1 })}
                      {chunk.page_number != null ? (
                        <span style={{ fontWeight: 400, color: "var(--console-text-muted, #64748b)", marginLeft: 8 }}>
                          p.{chunk.page_number}
                        </span>
                      ) : null}
                    </div>
                    <div style={{ marginTop: 8, fontSize: "0.75rem", color: "var(--console-text-secondary, #475569)", lineHeight: 1.7, whiteSpace: "pre-wrap" }}>
                      {chunk.content.slice(0, 320)}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );

  const renderAssistant = () => (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(260px, 0.9fr) minmax(0, 1.4fr)",
        gap: 18,
        height: "100%",
        minHeight: 0,
      }}
    >
      <div style={{ display: "grid", gap: 18, minHeight: 0 }}>
        {renderAssetList()}
        <div style={{ ...surfaceStyle, padding: 18 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <MessagesSquare size={16} />
            <strong>{t("study.workspace.promptTitle")}</strong>
          </div>
          <div
            role="tablist"
            aria-label={t("study.workspace.scopeToggleLabel")}
            style={{
              display: "inline-flex",
              gap: 4,
              padding: 3,
              borderRadius: 999,
              background: "rgba(15, 23, 42, 0.05)",
              marginBottom: 12,
            }}
          >
            <button
              type="button"
              role="tab"
              aria-selected={assistantScope === "asset"}
              onClick={() => setAssistantScope("asset")}
              disabled={assistantStreaming}
              style={{
                padding: "5px 12px",
                fontSize: "0.6875rem",
                fontWeight: 600,
                borderRadius: 999,
                border: "none",
                cursor: assistantStreaming ? "default" : "pointer",
                background:
                  assistantScope === "asset"
                    ? "#fff"
                    : "transparent",
                color:
                  assistantScope === "asset"
                    ? "var(--console-text-primary, #0f172a)"
                    : "var(--console-text-muted, #64748b)",
                boxShadow:
                  assistantScope === "asset"
                    ? "0 2px 6px rgba(15,23,42,0.08)"
                    : undefined,
              }}
              data-testid="assistant-scope-asset"
            >
              {t("study.workspace.scopeAsset")}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={assistantScope === "notebook"}
              onClick={() => setAssistantScope("notebook")}
              disabled={assistantStreaming}
              style={{
                padding: "5px 12px",
                fontSize: "0.6875rem",
                fontWeight: 600,
                borderRadius: 999,
                border: "none",
                cursor: assistantStreaming ? "default" : "pointer",
                background:
                  assistantScope === "notebook"
                    ? "#fff"
                    : "transparent",
                color:
                  assistantScope === "notebook"
                    ? "var(--console-text-primary, #0f172a)"
                    : "var(--console-text-muted, #64748b)",
                boxShadow:
                  assistantScope === "notebook"
                    ? "0 2px 6px rgba(15,23,42,0.08)"
                    : undefined,
              }}
              data-testid="assistant-scope-notebook"
              title={t("study.workspace.scopeNotebookHint")}
            >
              {t("study.workspace.scopeNotebook")}
            </button>
          </div>
          <div style={{ display: "grid", gap: 8 }}>
            {[
              "study.workspace.prompts.summary",
              "study.workspace.prompts.keyIdeas",
              "study.workspace.prompts.confusions",
              "study.workspace.prompts.memory",
            ].map((key) => {
              const promptDisabled =
                assistantStreaming ||
                (assistantScope === "asset" &&
                  (!selectedAsset || selectedAsset.status !== "indexed")) ||
                (assistantScope === "notebook" &&
                  !assets.some((a) => a.status === "indexed"));
              return (
                <button
                  key={key}
                  type="button"
                  disabled={promptDisabled}
                  onClick={() => {
                    void handleAssistantPrompt(t(key));
                  }}
                  style={{
                    padding: "10px 12px",
                    borderRadius: 12,
                    border: "1px solid rgba(15, 23, 42, 0.08)",
                    background: "#fff",
                    cursor: promptDisabled ? "default" : "pointer",
                    textAlign: "left",
                    opacity: promptDisabled ? 0.55 : 1,
                  }}
                >
                  {t(key)}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <div style={{ ...surfaceStyle, padding: 18, display: "flex", flexDirection: "column", minHeight: 0 }}>
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: "0.75rem", fontWeight: 700, color: "var(--console-accent, var(--console-accent, #0D9488))", letterSpacing: "0.04em", textTransform: "uppercase" }}>
            {assistantScope === "notebook"
              ? t("study.workspace.scopeNotebook")
              : t("study.workspace.assistantTitle")}
          </div>
          <div style={{ marginTop: 6, fontSize: "0.875rem", color: "var(--console-text-muted, #64748b)", lineHeight: 1.6 }}>
            {assistantScope === "notebook"
              ? t("study.workspace.notebookAssistantBody", {
                  count: assets.filter((a) => a.status === "indexed").length,
                })
              : selectedAsset
                ? t("study.workspace.assistantBody", { title: selectedAsset.title || t("study.assets.untitled") })
                : t("study.workspace.pickAsset")}
          </div>
        </div>

        <div style={{ flex: 1, minHeight: 0, overflowY: "auto", display: "grid", gap: 12, paddingRight: 4 }}>
          {assistantMessages.length === 0 && !assistantStreaming ? (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                minHeight: 200,
                color: "var(--console-text-muted, #64748b)",
                textAlign: "center",
                fontSize: "0.8125rem",
                lineHeight: 1.7,
              }}
            >
              {t("study.workspace.assistantEmpty")}
            </div>
          ) : null}

          {assistantMessages.map((message, index) => (
            <div
              key={`${message.role}-${index}`}
              style={{
                padding: "12px 14px",
                borderRadius: 16,
                background: message.role === "user"
                  ? "var(--console-accent-soft, rgba(13, 148, 136, 0.1))"
                  : "rgba(248, 250, 252, 0.95)",
                border: "1px solid rgba(15, 23, 42, 0.08)",
              }}
            >
              <div style={{ fontSize: "0.6875rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.04em", color: "var(--console-text-muted, #64748b)" }}>
                {message.role === "user" ? t("study.workspace.you") : t("study.workspace.ai")}
              </div>
              <div style={{ marginTop: 8, fontSize: "0.8125rem", color: "var(--console-text-primary, #0f172a)", lineHeight: 1.7, whiteSpace: "pre-wrap" }}>
                {message.content}
              </div>
              {message.sources && message.sources.length > 0 ? (
                <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {message.sources.slice(0, 4).map((source, sourceIndex) => {
                    // Resolve the data_item_id this source belongs to —
                    // for notebook-scope answers it can be a different
                    // asset than the currently selected one.
                    const sourceDataItemId =
                      source.data_item_id ||
                      (source.asset_id
                        ? assets.find((a) => a.id === source.asset_id)
                            ?.data_item_id || null
                        : selectedAsset?.data_item_id || null);
                    const canJump =
                      source.page_number != null && !!sourceDataItemId;
                    const jump = () => {
                      if (!canJump || !sourceDataItemId) return;
                      // If the source belongs to a different asset, swap
                      // the selection so the document tab loads it.
                      if (
                        source.asset_id &&
                        source.asset_id !== selectedAssetId
                      ) {
                        setSelectedAssetId(source.asset_id);
                      }
                      setTab("document");
                      window.setTimeout(() => {
                        window.dispatchEvent(
                          new CustomEvent("mrnote:open-pdf-page", {
                            detail: {
                              dataItemId: sourceDataItemId,
                              pageNumber: source.page_number,
                            },
                          }),
                        );
                      }, 100);
                    };
                    const baseStyle: React.CSSProperties = {
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                      padding: "6px 8px",
                      borderRadius: 999,
                      background: "rgba(15, 23, 42, 0.06)",
                      fontSize: "0.6875rem",
                      color: "var(--console-text-muted, #64748b)",
                      border: "none",
                    };
                    const label = (() => {
                      const parts: string[] = [];
                      if (source.asset_title) parts.push(source.asset_title);
                      if (source.heading) parts.push(source.heading);
                      if (parts.length === 0)
                        parts.push(t("study.workspace.source"));
                      return parts.join(" · ");
                    })();
                    if (canJump) {
                      return (
                        <button
                          type="button"
                          key={`${source.chunk_id || sourceIndex}`}
                          onClick={jump}
                          style={{
                            ...baseStyle,
                            cursor: "pointer",
                            background: "rgba(13, 148, 136, 0.1)",
                            color: "var(--console-accent, #0d9488)",
                          }}
                          data-testid="study-source-pill"
                          title={t("study.workspace.openSource")}
                        >
                          {label}
                          {` · p.${source.page_number}`}
                        </button>
                      );
                    }
                    return (
                      <span
                        key={`${source.chunk_id || sourceIndex}`}
                        style={baseStyle}
                      >
                        {label}
                        {source.page_number != null
                          ? ` · p.${source.page_number}`
                          : ""}
                      </span>
                    );
                  })}
                </div>
              ) : null}
            </div>
          ))}

          {assistantStreaming ? (
            <div
              style={{
                padding: "12px 14px",
                borderRadius: 16,
                background: "rgba(248, 250, 252, 0.95)",
                border: "1px solid rgba(15, 23, 42, 0.08)",
              }}
            >
              <div style={{ fontSize: "0.6875rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.04em", color: "var(--console-text-muted, #64748b)" }}>
                {t("study.workspace.ai")}
              </div>
              <div style={{ marginTop: 8, fontSize: "0.8125rem", color: "var(--console-text-primary, #0f172a)", lineHeight: 1.7, whiteSpace: "pre-wrap" }}>
                {streamingReply || t("study.workspace.streaming")}
              </div>
            </div>
          ) : null}
        </div>

        {assistantError ? (
          <div
            role="alert"
            style={{
              marginTop: 12,
              padding: "8px 10px",
              borderRadius: 12,
              background: "rgba(220, 38, 38, 0.08)",
              color: "#b91c1c",
              fontSize: "0.75rem",
            }}
          >
            {assistantError}
          </div>
        ) : null}

        <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
          {(() => {
            const indexedCount = assets.filter((a) => a.status === "indexed").length;
            const ready =
              assistantScope === "asset"
                ? !!selectedAsset && selectedAsset.status === "indexed"
                : indexedCount > 0;
            const inputDisabled = !ready || assistantStreaming;
            const hintKey = ready
              ? assistantScope === "notebook"
                ? "study.workspace.notebookAssistantHint"
                : "study.workspace.assistantHint"
              : "study.workspace.assistantDisabled";
            return (
              <>
                <textarea
                  value={assistantInput}
                  onChange={(event) => setAssistantInput(event.target.value)}
                  placeholder={t("study.workspace.assistantPlaceholder")}
                  disabled={inputDisabled}
                  rows={4}
                  style={{
                    width: "100%",
                    resize: "none",
                    borderRadius: 14,
                    border: "1px solid rgba(15, 23, 42, 0.1)",
                    padding: "12px 14px",
                    fontSize: "0.8125rem",
                    lineHeight: 1.6,
                    background: "#fff",
                  }}
                />
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: 12,
                  }}
                >
                  <span
                    style={{
                      fontSize: "0.75rem",
                      color: "var(--console-text-muted, #64748b)",
                    }}
                  >
                    {t(hintKey, { count: indexedCount })}
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      void handleAssistantSubmit();
                    }}
                    disabled={
                      !assistantInput.trim() || inputDisabled
                    }
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                      padding: "8px 14px",
                      borderRadius: 999,
                      border: "none",
                      background:
                        "var(--console-cta-gradient, linear-gradient(135deg, #F97316, #EA6A0F))",
                      color: "#fff",
                      cursor: "pointer",
                      opacity:
                        !assistantInput.trim() || inputDisabled ? 0.6 : 1,
                    }}
                  >
                    {assistantStreaming ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <Sparkles size={14} />
                    )}
                    {assistantStreaming
                      ? t("study.workspace.sending")
                      : t("study.workspace.send")}
                  </button>
                </div>
              </>
            );
          })()}
        </div>
      </div>
    </div>
  );

  const renderDocumentWorkspace = () => (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(260px, 0.72fr) minmax(0, 1.65fr)",
        gap: 18,
        height: "100%",
        minHeight: 0,
      }}
    >
      {renderAssetList()}

      <div
        style={{
          ...surfaceStyle,
          display: "flex",
          minHeight: 0,
          overflow: "hidden",
          padding: 0,
        }}
      >
        {!selectedAsset ? (
          <div
            style={{
              display: "grid",
              flex: 1,
              placeItems: "center",
              color: "var(--console-text-muted, #64748b)",
              fontSize: "0.875rem",
            }}
          >
            {t("study.workspace.pickAsset")}
          </div>
        ) : !selectedAsset.data_item_id ? (
          <div
            style={{
              display: "grid",
              flex: 1,
              placeItems: "center",
              padding: 24,
              textAlign: "center",
              color: "var(--console-text-muted, #64748b)",
            }}
          >
            <div style={{ maxWidth: 360, lineHeight: 1.7 }}>
              <FileText size={34} strokeWidth={1.4} />
              <h3
                style={{
                  margin: "12px 0 6px",
                  color: "var(--console-text-primary, #0f172a)",
                }}
              >
                {t("study.workspace.documentTitle")}
              </h3>
              <p style={{ margin: 0, fontSize: "0.8125rem" }}>
                {t("study.workspace.documentUnavailable")}
              </p>
            </div>
          </div>
        ) : (
          <ReferenceDocumentWindow
            notebookId={notebookId}
            assetId={selectedAsset.id}
            dataItemId={selectedAsset.data_item_id}
          />
        )}
      </div>
    </div>
  );

  return (
    <div className="study-window" data-testid="study-window" style={{ height: "100%", display: "flex", flexDirection: "column", padding: 16, gap: 16 }}>
      <div
        style={{
          ...surfaceStyle,
          padding: 16,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <div>
          <div style={{ fontSize: "0.75rem", fontWeight: 700, color: "var(--console-accent, var(--console-accent, #0D9488))", letterSpacing: "0.04em", textTransform: "uppercase" }}>
            {t("study.workspace.headerKicker")}
          </div>
          <h1 style={{ margin: "6px 0 0", fontSize: "1.2rem", color: "var(--console-text-primary, #0f172a)" }}>
            {t("study.workspace.headerTitle")}
          </h1>
          <p style={{ margin: "8px 0 0", fontSize: "0.8125rem", color: "var(--console-text-muted, #64748b)", lineHeight: 1.6, maxWidth: 760 }}>
            {t("study.workspace.headerBody")}
          </p>
        </div>

        <div className="study-window__tabs" role="tablist" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={tab === item.id}
              data-testid={item.testId}
              onClick={() => setTab(item.id)}
              disabled={item.id === "review" && !reviewingDeckId}
              title={
                item.id === "review" && !reviewingDeckId
                  ? t("study.workspace.reviewDisabled")
                  : ""
              }
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "8px 12px",
                borderRadius: 999,
                border: tab === item.id
                  ? "1px solid rgba(13, 148, 136, 0.24)"
                  : "1px solid rgba(15, 23, 42, 0.08)",
                background: tab === item.id
                  ? "rgba(239, 246, 255, 0.96)"
                  : "#fff",
                color: tab === item.id
                  ? "var(--console-accent, var(--console-accent, #0D9488))"
                  : "var(--console-text-muted, #64748b)",
                cursor: item.id === "review" && !reviewingDeckId ? "default" : "pointer",
              }}
            >
              <item.icon size={14} />
              {t(item.labelKey)}
            </button>
          ))}
        </div>
      </div>

      <div className="study-window__body" style={{ flex: 1, minHeight: 0 }}>
        {tab === "overview" && renderOverview()}
        {tab === "document" && renderDocumentWorkspace()}
        {tab === "progress" && (
          <StudyProgressPanel
            notebookId={notebookId}
            generatedPages={generatedPages}
            onGoToOverview={() => setTab("overview")}
            onGoToAssistant={() => setTab("assistant")}
            onGoToDecks={() => setTab("decks")}
            onStartReview={handleStartReview}
            onOpenPage={openNotebookPage}
            onOpenMemoryGraph={handleOpenMemoryGraph}
          />
        )}
        {tab === "assistant" && renderAssistant()}
        {tab === "decks" && (
          <DecksPanel notebookId={notebookId} onStartReview={handleStartReview} />
        )}
        {tab === "review" && reviewingDeckId && (
          <ReviewSession
            deckId={reviewingDeckId}
            onExit={() => setTab("decks")}
          />
        )}
      </div>
    </div>
  );
}
