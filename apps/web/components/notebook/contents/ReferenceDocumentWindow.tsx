"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  Download,
  FileText,
  History,
  Loader2,
  RefreshCw,
  Save,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { apiGet, apiPut } from "@/lib/api";
import { getApiHttpBaseUrl } from "@/lib/env";
import { getSafeExternalUrl } from "@/lib/security";

// Heavy components are dynamically imported so the bundle only loads them
// when the user actually opens a PDF or an Office document.
const PDFViewer = dynamic(() => import("./PDFViewer"), {
  ssr: false,
  loading: () => (
    <div className="reference-document-window__inline-loading">
      <Loader2 size={20} className="animate-spin" />
    </div>
  ),
});
const OnlyOfficeEditor = dynamic(() => import("./OnlyOfficeEditor"), {
  ssr: false,
  loading: () => (
    <div className="reference-document-window__inline-loading">
      <Loader2 size={20} className="animate-spin" />
    </div>
  ),
});
const VersionsPanel = dynamic(() => import("./pdf/VersionsPanel"), {
  ssr: false,
});

interface ReferenceDocumentWindowProps {
  notebookId: string;
  assetId: string;
  dataItemId: string;
}

interface StudyAsset {
  id: string;
  data_item_id?: string | null;
  title: string;
  asset_type: string;
  status: string;
  total_chunks: number;
}

interface DataItem {
  id: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  preview_url?: string | null;
  download_url?: string | null;
}

interface DataItemContent {
  id: string;
  filename: string;
  media_type: string;
  content: string;
  editable: boolean;
}

const EDITABLE_EXTENSIONS = [
  ".txt",
  ".md",
  ".markdown",
  ".csv",
  ".tsv",
  ".json",
  ".yaml",
  ".yml",
  ".toml",
  ".ini",
  ".cfg",
  ".log",
  ".tex",
  ".py",
  ".js",
  ".jsx",
  ".ts",
  ".tsx",
  ".css",
  ".sql",
  ".sh",
  ".vue",
  ".svelte",
];

const OFFICE_EXTENSIONS = new Set([
  ".docx",
  ".doc",
  ".dotx",
  ".odt",
  ".rtf",
  ".xlsx",
  ".xls",
  ".xlsm",
  ".ods",
  ".pptx",
  ".ppt",
  ".ppsx",
  ".odp",
]);

function fileExtension(filename: string): string {
  if (!filename || !filename.includes(".")) return "";
  return `.${filename.toLowerCase().split(".").pop() || ""}`;
}

function canEditAsText(item: DataItem | null): boolean {
  if (!item) return false;
  const mediaType = item.media_type.toLowerCase();
  if (mediaType.startsWith("text/")) return true;
  if (mediaType.includes("json") || mediaType.includes("javascript")) {
    return true;
  }
  return EDITABLE_EXTENSIONS.includes(fileExtension(item.filename));
}

function isPdfItem(item: DataItem | null): boolean {
  if (!item) return false;
  return (
    item.media_type.toLowerCase() === "application/pdf" ||
    fileExtension(item.filename) === ".pdf"
  );
}

function isImageItem(item: DataItem | null): boolean {
  return !!item && item.media_type.toLowerCase().startsWith("image/");
}

function isOfficeItem(item: DataItem | null): boolean {
  if (!item) return false;
  return OFFICE_EXTENSIONS.has(fileExtension(item.filename));
}

function humanSize(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export default function ReferenceDocumentWindow({
  notebookId,
  assetId,
  dataItemId,
}: ReferenceDocumentWindowProps) {
  const t = useTranslations("console-notebooks");
  const [asset, setAsset] = useState<StudyAsset | null>(null);
  const [item, setItem] = useState<DataItem | null>(null);
  const [content, setContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [contentError, setContentError] = useState<string | null>(null);
  const [officeSavedAt, setOfficeSavedAt] = useState<number | null>(null);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const resolvedDataItemId = item?.id || dataItemId || asset?.data_item_id || "";
  const editable = canEditAsText(item);
  const isPdf = isPdfItem(item);
  const isOffice = isOfficeItem(item);
  const isImage = isImageItem(item);
  const hasUnsavedChanges = content !== savedContent;

  const previewUrl = useMemo(() => {
    if (!resolvedDataItemId || (!isPdf && !isImage)) return "";
    const path = `/api/v1/data-items/${resolvedDataItemId}/preview`;
    const base = getSafeExternalUrl(`${getApiHttpBaseUrl()}${path}`) || "";
    if (!base || reloadKey === 0) return base;
    // After a version restore the bytes change but the URL doesn't, so
    // the browser will happily serve the stale cached PDF/image. Add a
    // version param to bust HTTP cache without changing the route.
    return `${base}${base.includes("?") ? "&" : "?"}_v=${reloadKey}`;
  }, [isImage, isPdf, reloadKey, resolvedDataItemId]);

  const downloadUrl = getSafeExternalUrl(item?.download_url || "") || "";

  const loadDocument = useCallback(async () => {
    if (!assetId && !dataItemId) {
      setError(t("references.documentMissing"));
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    setContentError(null);
    try {
      let nextAsset: StudyAsset | null = null;
      let nextDataItemId = dataItemId;
      if (assetId) {
        nextAsset = await apiGet<StudyAsset>(
          `/api/v1/notebooks/${notebookId}/study-assets/${assetId}`,
        );
        setAsset(nextAsset);
        nextDataItemId = nextAsset.data_item_id || nextDataItemId;
      }
      if (!nextDataItemId) {
        throw new Error(t("references.documentMissing"));
      }
      const nextItem = await apiGet<DataItem>(`/api/v1/data-items/${nextDataItemId}`);
      setItem(nextItem);

      if (canEditAsText(nextItem)) {
        try {
          const text = await apiGet<DataItemContent>(
            `/api/v1/data-items/${nextDataItemId}/content`,
          );
          setContent(text.content);
          setSavedContent(text.content);
        } catch (err) {
          setContentError(
            err instanceof Error ? err.message : t("references.contentLoadFailed"),
          );
          setContent("");
          setSavedContent("");
        }
      } else {
        setContent("");
        setSavedContent("");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t("references.loadFailed"));
      setItem(null);
    } finally {
      setLoading(false);
    }
  }, [assetId, dataItemId, notebookId, t]);

  useEffect(() => {
    void loadDocument();
  }, [loadDocument]);

  const saveContent = useCallback(async () => {
    if (!resolvedDataItemId || !editable || saving) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await apiPut<DataItemContent>(
        `/api/v1/data-items/${resolvedDataItemId}/content`,
        { content },
      );
      setContent(saved.content);
      setSavedContent(saved.content);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("references.saveFailed"));
    } finally {
      setSaving(false);
    }
  }, [content, editable, resolvedDataItemId, saving, t]);

  const handleOfficeSaved = useCallback(() => {
    setOfficeSavedAt(Date.now());
  }, []);

  if (loading) {
    return (
      <div className="reference-document-window reference-document-window--center">
        <Loader2 size={24} className="animate-spin" />
        <span>{t("common.loading")}</span>
      </div>
    );
  }

  if (error && !item) {
    return (
      <div className="reference-document-window reference-document-window--center">
        <AlertCircle size={28} />
        <strong>{error}</strong>
        <button type="button" onClick={loadDocument}>
          <RefreshCw size={14} />
          {t("references.retry")}
        </button>
      </div>
    );
  }

  return (
    <div className="reference-document-window">
      <header className="reference-document-window__toolbar">
        <div>
          <p>{asset?.asset_type?.toUpperCase() || item?.media_type || "FILE"}</p>
          <h2>{asset?.title || item?.filename || t("references.untitled")}</h2>
          <span>
            {item ? `${item.media_type} · ${humanSize(item.size_bytes)}` : ""}
            {officeSavedAt && isOffice ? (
              <span className="reference-document-window__saved-badge">
                {" · "}
                {t("office.saved")}
              </span>
            ) : null}
          </span>
        </div>
        <div className="reference-document-window__actions">
          {editable ? (
            <button
              type="button"
              onClick={saveContent}
              disabled={!hasUnsavedChanges || saving}
              data-testid="reference-document-save"
            >
              {saving ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Save size={14} />
              )}
              {saving
                ? t("references.saving")
                : hasUnsavedChanges
                  ? t("references.save")
                  : t("references.saved")}
            </button>
          ) : null}
          {resolvedDataItemId ? (
            <button
              type="button"
              onClick={() => setVersionsOpen((open) => !open)}
              data-testid="reference-document-versions-toggle"
              title={t("versions.title")}
            >
              <History size={14} />
              {t("versions.title")}
            </button>
          ) : null}
          {downloadUrl ? (
            <a href={downloadUrl} download={item?.filename}>
              <Download size={14} />
              {t("references.download")}
            </a>
          ) : null}
        </div>
      </header>

      {error ? (
        <div className="reference-document-window__error">
          <AlertCircle size={14} />
          {error}
        </div>
      ) : null}

      <main className="reference-document-window__body">
        {isOffice && resolvedDataItemId ? (
          <OnlyOfficeEditor
            key={`office-${resolvedDataItemId}-${reloadKey}`}
            dataItemId={resolvedDataItemId}
            onSaved={handleOfficeSaved}
            onError={(message) => setError(message)}
          />
        ) : isPdf && previewUrl ? (
          <PDFViewer
            key={`pdf-${resolvedDataItemId}-${reloadKey}`}
            url={previewUrl}
            filename={item?.filename}
            downloadUrl={downloadUrl || undefined}
            notebookId={notebookId}
            studyAssetId={asset?.id || assetId}
            documentTitle={asset?.title || item?.filename}
            dataItemId={resolvedDataItemId}
          />
        ) : editable ? (
          <section className="reference-document-window__editor">
            {contentError ? (
              <div className="reference-document-window__error">
                <AlertCircle size={14} />
                {contentError}
              </div>
            ) : null}
            <textarea
              value={content}
              onChange={(event) => setContent(event.target.value)}
              spellCheck={false}
              data-testid="reference-document-editor"
            />
          </section>
        ) : isImage && previewUrl ? (
          // eslint-disable-next-line @next/next/no-img-element -- presigned same-origin file previews are already validated server-side.
          <img
            className="reference-document-window__preview"
            src={previewUrl}
            alt={item?.filename || t("references.preview")}
          />
        ) : (
          <section className="reference-document-window__unsupported">
            <FileText size={38} strokeWidth={1.4} />
            <strong>{t("references.unsupportedTitle")}</strong>
            <span>{t("references.unsupportedBody")}</span>
            {downloadUrl ? (
              <a href={downloadUrl} download={item?.filename}>
                <Download size={14} />
                {t("references.download")}
              </a>
            ) : null}
          </section>
        )}

        {versionsOpen && resolvedDataItemId ? (
          <VersionsPanel
            open={versionsOpen}
            dataItemId={resolvedDataItemId}
            onClose={() => setVersionsOpen(false)}
            onRestored={() => {
              // Reload the editor / PDF so it picks up restored bytes.
              setReloadKey((k) => k + 1);
              void loadDocument();
            }}
          />
        ) : null}
      </main>
    </div>
  );
}
