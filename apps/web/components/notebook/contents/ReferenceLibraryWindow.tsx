"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import {
  AlertCircle,
  CheckCircle2,
  FileSpreadsheet,
  FileText,
  FileType2,
  FolderOpen,
  Loader2,
  Plus,
  Presentation,
  Search as SearchIcon,
  Tag as TagIcon,
  Upload,
  X,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { apiGet, apiPatch, apiPost } from "@/lib/api";
import { STUDY_UPLOAD_ACCEPT, uploadStudyAssets } from "@/lib/study-upload";
import { useWindowManager } from "@/components/notebook/WindowManager";
import { dispatchNotebookStudyChanged } from "@/lib/notebook-events";
import StorageUsageBadge from "./StorageUsageBadge";

interface StudyAsset {
  id: string;
  notebook_id: string;
  data_item_id?: string | null;
  title: string;
  asset_type: string;
  status: string;
  total_chunks: number;
  created_at: string;
  tags?: string[];
}

interface ReferenceLibraryWindowProps {
  notebookId: string;
}

type DocType = "docx" | "xlsx" | "pptx" | "pdf";

const STATUS_ICON_SIZE = 15;

const CREATE_OPTIONS: Array<{
  type: DocType;
  Icon: typeof FileText;
  labelKey: string;
}> = [
  { type: "docx", Icon: FileText, labelKey: "references.createDoc" },
  { type: "xlsx", Icon: FileSpreadsheet, labelKey: "references.createSheet" },
  { type: "pptx", Icon: Presentation, labelKey: "references.createSlides" },
  { type: "pdf", Icon: FileType2, labelKey: "references.createPdf" },
];

function formatAssetDate(value: string): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(value));
  } catch {
    return "";
  }
}

export default function ReferenceLibraryWindow({
  notebookId,
}: ReferenceLibraryWindowProps) {
  const t = useTranslations("console-notebooks");
  const { openWindow } = useWindowManager();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const createMenuRef = useRef<HTMLDivElement | null>(null);
  const [assets, setAssets] = useState<StudyAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{
    done: number;
    total: number;
  } | null>(null);
  const [creating, setCreating] = useState<DocType | null>(null);
  const [createMenuOpen, setCreateMenuOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [activeTags, setActiveTags] = useState<string[]>([]);
  const [tagEditingId, setTagEditingId] = useState<string | null>(null);
  const [tagDraft, setTagDraft] = useState("");
  const [savingTagsId, setSavingTagsId] = useState<string | null>(null);

  const loadAssets = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet<{ items: StudyAsset[] }>(
        `/api/v1/notebooks/${notebookId}/study-assets?limit=200`,
      );
      setAssets(data.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("references.loadFailed"));
      setAssets([]);
    } finally {
      setLoading(false);
    }
  }, [notebookId, t]);

  useEffect(() => {
    void loadAssets();
  }, [loadAssets]);

  // Close the create menu when clicking outside.
  useEffect(() => {
    if (!createMenuOpen) return;
    const handle = (event: MouseEvent) => {
      if (
        createMenuRef.current &&
        !createMenuRef.current.contains(event.target as Node)
      ) {
        setCreateMenuOpen(false);
      }
    };
    window.addEventListener("mousedown", handle);
    return () => window.removeEventListener("mousedown", handle);
  }, [createMenuOpen]);

  const statusLabel = useCallback(
    (status: string): string => {
      const labels: Record<string, string> = {
        pending: t("study.assets.statusPending"),
        parsing: t("study.assets.statusParsing"),
        chunked: t("study.assets.statusChunked"),
        indexed: t("study.assets.statusIndexed"),
        failed: t("study.assets.statusFailed"),
      };
      return labels[status] ?? status;
    },
    [t],
  );

  const openUploadPicker = useCallback(() => {
    setError(null);
    inputRef.current?.click();
  }, []);

  const handleFiles = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const files = event.target.files ? Array.from(event.target.files) : [];
      if (inputRef.current) inputRef.current.value = "";
      if (!files.length) return;
      setUploading(true);
      setError(null);
      setUploadProgress({ done: 0, total: files.length });
      try {
        await uploadStudyAssets(notebookId, files, (done, total) => {
          setUploadProgress({ done, total });
        });
        await loadAssets();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setUploading(false);
        setUploadProgress(null);
      }
    },
    [loadAssets, notebookId],
  );

  const openReference = useCallback(
    (asset: StudyAsset) => {
      openWindow({
        type: "reference_document",
        title: asset.title || t("references.untitled"),
        meta: {
          notebookId,
          assetId: asset.id,
          dataItemId: asset.data_item_id || "",
        },
      });
    },
    [notebookId, openWindow, t],
  );

  // ---- Tag editing -----------------------------------------------------

  const allTags = useMemo(() => {
    const set = new Set<string>();
    for (const a of assets) {
      for (const tag of a.tags || []) {
        if (tag) set.add(tag);
      }
    }
    return Array.from(set).sort();
  }, [assets]);

  const filteredAssets = useMemo(() => {
    const q = search.trim().toLowerCase();
    return assets.filter((asset) => {
      if (
        activeTags.length > 0 &&
        !activeTags.every((t) => (asset.tags || []).includes(t))
      ) {
        return false;
      }
      if (q) {
        const haystack = [
          asset.title || "",
          asset.asset_type || "",
          ...(asset.tags || []),
        ]
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      return true;
    });
  }, [activeTags, assets, search]);

  const toggleTagFilter = useCallback((tag: string) => {
    setActiveTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
    );
  }, []);

  const beginEditTags = useCallback((asset: StudyAsset) => {
    setTagEditingId(asset.id);
    setTagDraft((asset.tags || []).join(", "));
  }, []);

  const cancelEditTags = useCallback(() => {
    setTagEditingId(null);
    setTagDraft("");
  }, []);

  const commitTags = useCallback(
    async (assetId: string) => {
      if (savingTagsId) return;
      const tags = tagDraft
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean)
        .slice(0, 20);
      setSavingTagsId(assetId);
      try {
        const updated = await apiPatch<StudyAsset>(
          `/api/v1/notebooks/${notebookId}/study-assets/${assetId}/tags`,
          { tags },
        );
        setAssets((prev) =>
          prev.map((a) => (a.id === assetId ? { ...a, tags: updated.tags || [] } : a)),
        );
        cancelEditTags();
      } catch (err) {
        setError(err instanceof Error ? err.message : t("references.saveFailed"));
      } finally {
        setSavingTagsId(null);
      }
    },
    [cancelEditTags, notebookId, savingTagsId, t, tagDraft],
  );

  const handleTagInputKey = useCallback(
    (event: KeyboardEvent<HTMLInputElement>, assetId: string) => {
      if (event.key === "Enter") {
        event.preventDefault();
        void commitTags(assetId);
      } else if (event.key === "Escape") {
        event.preventDefault();
        cancelEditTags();
      }
    },
    [cancelEditTags, commitTags],
  );

  const createBlankDocument = useCallback(
    async (docType: DocType) => {
      if (creating) return;
      setCreating(docType);
      setError(null);
      setCreateMenuOpen(false);
      try {
        const defaultTitle = t("references.untitled");
        const promptedTitle = window.prompt(
          t("references.createPrompt"),
          defaultTitle,
        );
        if (promptedTitle === null) {
          // user cancelled
          return;
        }
        const title = promptedTitle.trim() || defaultTitle;
        const created = await apiPost<StudyAsset>(
          `/api/v1/notebooks/${notebookId}/references/create`,
          { title, doc_type: docType },
        );
        dispatchNotebookStudyChanged(notebookId);
        await loadAssets();
        openReference(created);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : t("references.createFailed"),
        );
      } finally {
        setCreating(null);
      }
    },
    [creating, loadAssets, notebookId, openReference, t],
  );

  const busy = uploading || !!creating;

  return (
    <div className="reference-library-window">
      <header className="reference-library-window__header">
        <div>
          <p>{t("references.kicker")}</p>
          <h2>{t("references.title")}</h2>
          <span>{t("references.subtitle")}</span>
        </div>
        <div className="reference-library-window__header-actions">
          <StorageUsageBadge />
          <div
            className="reference-library-window__create"
            ref={createMenuRef}
          >
            <button
              type="button"
              onClick={() => setCreateMenuOpen((open) => !open)}
              disabled={busy}
              data-testid="references-create-button"
              aria-haspopup="menu"
              aria-expanded={createMenuOpen}
            >
              {creating ? (
                <Loader2 size={15} className="animate-spin" />
              ) : (
                <Plus size={15} />
              )}
              {creating
                ? t("references.creating")
                : t("references.create")}
            </button>
            {createMenuOpen ? (
              <div
                className="reference-library-window__create-menu"
                role="menu"
                data-testid="references-create-menu"
              >
                {CREATE_OPTIONS.map((option) => (
                  <button
                    key={option.type}
                    type="button"
                    role="menuitem"
                    onClick={() => void createBlankDocument(option.type)}
                    disabled={busy}
                    data-testid={`references-create-${option.type}`}
                  >
                    <option.Icon size={15} />
                    <span>{t(option.labelKey)}</span>
                  </button>
                ))}
              </div>
            ) : null}
          </div>

          <button
            type="button"
            onClick={openUploadPicker}
            disabled={busy}
            data-testid="references-upload-button"
            className="reference-library-window__upload"
          >
            {uploading ? (
              <Loader2 size={15} className="animate-spin" />
            ) : (
              <Upload size={15} />
            )}
            {uploading && uploadProgress
              ? t("study.assets.uploading", uploadProgress)
              : t("references.upload")}
          </button>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept={STUDY_UPLOAD_ACCEPT}
            onChange={handleFiles}
            data-testid="references-upload-input"
          />
        </div>
      </header>

      {error ? (
        <div className="reference-library-window__error">
          <AlertCircle size={14} />
          {error}
        </div>
      ) : null}

      {assets.length > 0 ? (
        <div className="reference-library-window__filters">
          <div className="reference-library-window__search">
            <SearchIcon size={14} />
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t("references.searchPlaceholder")}
              data-testid="references-search"
            />
          </div>
          {allTags.length > 0 ? (
            <div
              className="reference-library-window__tag-filters"
              role="group"
              aria-label={t("references.tagFilterLabel")}
            >
              <TagIcon size={12} />
              {allTags.map((tag) => {
                const active = activeTags.includes(tag);
                return (
                  <button
                    key={tag}
                    type="button"
                    onClick={() => toggleTagFilter(tag)}
                    className={
                      active
                        ? "reference-library-window__tag is-active"
                        : "reference-library-window__tag"
                    }
                    data-testid="references-tag-filter"
                  >
                    {tag}
                  </button>
                );
              })}
              {activeTags.length > 0 ? (
                <button
                  type="button"
                  onClick={() => setActiveTags([])}
                  className="reference-library-window__tag-clear"
                  title={t("references.clearTagFilters")}
                  aria-label={t("references.clearTagFilters")}
                >
                  <X size={11} />
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}

      <main className="reference-library-window__body">
        {loading ? (
          <div className="reference-library-window__empty">
            <Loader2 size={24} className="animate-spin" />
            <span>{t("common.loading")}</span>
          </div>
        ) : assets.length === 0 ? (
          <div className="reference-library-window__empty">
            <FolderOpen size={34} strokeWidth={1.4} />
            <strong>{t("references.empty")}</strong>
            <span>{t("references.emptyHint")}</span>
          </div>
        ) : filteredAssets.length === 0 ? (
          <div className="reference-library-window__empty">
            <SearchIcon size={28} strokeWidth={1.4} />
            <strong>{t("references.noMatches")}</strong>
          </div>
        ) : (
          <div className="reference-library-window__grid">
            {filteredAssets.map((asset) => {
              const editing = tagEditingId === asset.id;
              return (
                <div
                  key={asset.id}
                  className="reference-library-window__item-wrap"
                  data-testid="reference-asset-card"
                >
                  <button
                    type="button"
                    className="reference-library-window__item"
                    onClick={() => openReference(asset)}
                  >
                    <span className="reference-library-window__file-icon">
                      <FileText size={18} />
                    </span>
                    <span className="reference-library-window__item-copy">
                      <strong>{asset.title || t("references.untitled")}</strong>
                      <small>
                        {asset.asset_type.toUpperCase()} ·{" "}
                        {t("study.assets.chunks", { count: asset.total_chunks })}
                      </small>
                      <em>{formatAssetDate(asset.created_at)}</em>
                    </span>
                    <span className="reference-library-window__status">
                      {asset.status === "indexed" ? (
                        <CheckCircle2 size={STATUS_ICON_SIZE} />
                      ) : asset.status === "failed" ? (
                        <AlertCircle size={STATUS_ICON_SIZE} />
                      ) : (
                        <Loader2
                          size={STATUS_ICON_SIZE}
                          className="animate-spin"
                        />
                      )}
                      {statusLabel(asset.status)}
                    </span>
                  </button>
                  <div className="reference-library-window__tag-row">
                    {(asset.tags || []).map((tag) => (
                      <span
                        key={tag}
                        className="reference-library-window__tag-chip"
                      >
                        {tag}
                      </span>
                    ))}
                    {editing ? (
                      <span className="reference-library-window__tag-edit">
                        <input
                          type="text"
                          autoFocus
                          value={tagDraft}
                          onChange={(e) => setTagDraft(e.target.value)}
                          onKeyDown={(e) => handleTagInputKey(e, asset.id)}
                          placeholder={t("references.tagInputPlaceholder")}
                        />
                        <button
                          type="button"
                          onClick={() => void commitTags(asset.id)}
                          disabled={savingTagsId === asset.id}
                        >
                          {savingTagsId === asset.id ? (
                            <Loader2 size={11} className="animate-spin" />
                          ) : (
                            <CheckCircle2 size={11} />
                          )}
                        </button>
                        <button
                          type="button"
                          onClick={cancelEditTags}
                          disabled={savingTagsId === asset.id}
                        >
                          <X size={11} />
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="reference-library-window__tag-edit-button"
                        onClick={() => beginEditTags(asset)}
                        title={t("references.editTags")}
                        aria-label={t("references.editTags")}
                      >
                        <TagIcon size={11} />
                        {(asset.tags || []).length === 0
                          ? t("references.addTags")
                          : t("references.editTagsShort")}
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}
