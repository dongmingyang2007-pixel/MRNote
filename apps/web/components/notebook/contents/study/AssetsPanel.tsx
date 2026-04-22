"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BookOpen, Loader2, CheckCircle, AlertCircle, FileText, Upload } from "lucide-react";
import { useTranslations } from "next-intl";
import { apiGet } from "@/lib/api";
import { STUDY_UPLOAD_ACCEPT, uploadStudyAssets } from "@/lib/study-upload";

interface StudyAsset {
  id: string;
  notebook_id: string;
  title: string;
  asset_type: string;
  status: string;
  total_chunks: number;
  created_at: string;
}

interface StudyChunk {
  id: string;
  chunk_index: number;
  heading: string;
  content: string;
  page_number: number | null;
}

interface AssetsPanelProps {
  notebookId: string;
}

const STATUS_ICONS: Record<string, React.ReactNode> = {
  indexed: <CheckCircle size={14} style={{ color: "var(--console-success)" }} />,
  failed: <AlertCircle size={14} style={{ color: "var(--console-error)" }} />,
  pending: <Loader2 size={14} className="animate-spin" style={{ color: "var(--console-text-muted)" }} />,
  parsing: <Loader2 size={14} className="animate-spin" style={{ color: "var(--console-accent)" }} />,
  chunked: <Loader2 size={14} className="animate-spin" style={{ color: "var(--console-accent)" }} />,
};

export default function AssetsPanel({ notebookId }: AssetsPanelProps) {
  const t = useTranslations("console-notebooks");
  const [assets, setAssets] = useState<StudyAsset[]>([]);
  const [selectedAsset, setSelectedAsset] = useState<StudyAsset | null>(null);
  const [chunks, setChunks] = useState<StudyChunk[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{ done: number; total: number } | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Status labels use i18n via a lookup inside the component (avoids top-level hook in object literal)
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

  const fetchAssets = useCallback(async () => {
    try {
      const data = await apiGet<{ items: StudyAsset[] }>(
        `/api/v1/notebooks/${notebookId}/study`,
      );
      setAssets(data.items || []);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [notebookId]);

  useEffect(() => {
    fetchAssets();
  }, [fetchAssets]);

  const fetchChunks = useCallback(async (assetId: string) => {
    try {
      const data = await apiGet<{ items: StudyChunk[] }>(
        `/api/v1/notebooks/${notebookId}/study/${assetId}/chunks?limit=50`,
      );
      setChunks(data.items || []);
    } catch {
      /* ignore */
    }
  }, [notebookId]);

  const handleAssetClick = useCallback((asset: StudyAsset) => {
    setSelectedAsset(asset);
    if (asset.status === "indexed") {
      fetchChunks(asset.id);
    }
  }, [fetchChunks]);

  const handleBack = useCallback(() => {
    setSelectedAsset(null);
    setChunks([]);
  }, []);

  const handleOpenUpload = useCallback(() => {
    setUploadError(null);
    fileInputRef.current?.click();
  }, []);

  const handleFilesSelected = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files ? Array.from(e.target.files) : [];
      if (fileInputRef.current) fileInputRef.current.value = "";
      if (files.length === 0) return;
      setUploadError(null);
      setUploading(true);
      setUploadProgress({ done: 0, total: files.length });
      try {
        await uploadStudyAssets(notebookId, files, (done, total) =>
          setUploadProgress({ done, total }),
        );
        await fetchAssets();
      } catch (err) {
        setUploadError(err instanceof Error ? err.message : String(err));
      } finally {
        setUploading(false);
        setUploadProgress(null);
      }
    },
    [notebookId, fetchAssets],
  );

  // Asset detail view
  if (selectedAsset) {
    return (
      <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
        <div style={{
          padding: "12px 16px",
          borderBottom: "1px solid var(--console-border-subtle)",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}>
          <button
            onClick={handleBack}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: "var(--console-accent)",
              fontSize: "0.8125rem",
              padding: 0,
            }}
          >
            {t("study.assets.back")}
          </button>
          <span style={{
            fontSize: "0.875rem",
            fontWeight: 600,
            color: "var(--console-text-primary)",
          }}>
            {selectedAsset.title}
          </span>
          <span style={{ fontSize: "0.75rem", color: "var(--console-text-muted)" }}>
            {t("study.assets.chunks", { count: selectedAsset.total_chunks })}
          </span>
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: "12px 16px" }}>
          {selectedAsset.status !== "indexed" ? (
            <div style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              height: "100%",
              color: "var(--console-text-muted)",
              gap: 8,
            }}>
              {STATUS_ICONS[selectedAsset.status]}
              <span style={{ fontSize: "0.8125rem" }}>{statusLabel(selectedAsset.status)}</span>
            </div>
          ) : chunks.length === 0 ? (
            <div style={{ color: "var(--console-text-muted)", fontSize: "0.8125rem", textAlign: "center", marginTop: 32 }}>
              {t("study.assets.noChunks")}
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {chunks.map((chunk) => (
                <div
                  key={chunk.id}
                  style={{
                    padding: "10px 12px",
                    borderRadius: "var(--console-radius-sm)",
                    background: "var(--console-surface)",
                    border: "1px solid var(--console-border-subtle)",
                    fontSize: "0.8125rem",
                  }}
                >
                  {chunk.heading && (
                    <div style={{
                      fontWeight: 600,
                      fontSize: "0.75rem",
                      color: "var(--console-text-secondary)",
                      marginBottom: 4,
                    }}>
                      {chunk.heading}
                      {chunk.page_number != null && (
                        <span style={{ color: "var(--console-text-muted)", fontWeight: 400, marginLeft: 8 }}>
                          p.{chunk.page_number}
                        </span>
                      )}
                    </div>
                  )}
                  <div style={{
                    color: "var(--console-text-primary)",
                    lineHeight: 1.5,
                    whiteSpace: "pre-wrap",
                    maxHeight: 120,
                    overflow: "hidden",
                  }}>
                    {chunk.content}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  // Asset list view
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <div style={{
        padding: "12px 16px",
        borderBottom: "1px solid var(--console-border-subtle)",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        gap: 8,
      }}>
        <span style={{
          fontSize: "0.875rem",
          fontWeight: 600,
          color: "var(--console-text-primary)",
        }}>
          {t("study.assets.title")}
        </span>
        <button
          type="button"
          data-testid="study-upload-button"
          onClick={handleOpenUpload}
          disabled={uploading}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "6px 10px",
            borderRadius: "var(--console-radius-sm)",
            border: "1px solid var(--console-border-subtle)",
            background: uploading ? "var(--console-surface)" : "var(--console-accent)",
            color: uploading ? "var(--console-text-muted)" : "#fff",
            fontSize: "0.75rem",
            cursor: uploading ? "default" : "pointer",
          }}
        >
          {uploading ? (
            <>
              <Loader2 size={12} className="animate-spin" />
              {uploadProgress
                ? t("study.assets.uploading", {
                    done: uploadProgress.done,
                    total: uploadProgress.total,
                  })
                : t("study.assets.uploading", { done: 0, total: 1 })}
            </>
          ) : (
            <>
              <Upload size={12} />
              {t("study.assets.upload")}
            </>
          )}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={STUDY_UPLOAD_ACCEPT}
          onChange={handleFilesSelected}
          style={{ display: "none" }}
          data-testid="study-upload-input"
        />
      </div>
      {uploadError && (
        <div style={{
          padding: "8px 16px",
          fontSize: "0.75rem",
          color: "var(--console-error)",
          background: "var(--console-surface)",
          borderBottom: "1px solid var(--console-border-subtle)",
        }}>
          {uploadError}
        </div>
      )}

      <div style={{ flex: 1, overflowY: "auto", padding: "12px 16px" }}>
        {loading ? (
          <div style={{ display: "flex", justifyContent: "center", padding: 32 }}>
            <Loader2 size={20} className="animate-spin" style={{ color: "var(--console-text-muted)" }} />
          </div>
        ) : assets.length === 0 ? (
          <div style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            height: "100%",
            gap: 12,
            color: "var(--console-text-muted)",
          }}>
            <BookOpen size={32} strokeWidth={1.2} />
            <span style={{ fontSize: "0.8125rem" }}>{t("study.assets.empty")}</span>
            <span style={{ fontSize: "0.75rem" }}>{t("study.assets.emptyHint")}</span>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {assets.map((asset) => (
              <button
                key={asset.id}
                onClick={() => handleAssetClick(asset)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "10px 12px",
                  borderRadius: "var(--console-radius-sm)",
                  background: "var(--console-surface)",
                  border: "1px solid var(--console-border-subtle)",
                  cursor: "pointer",
                  textAlign: "left",
                  width: "100%",
                }}
              >
                <FileText size={16} style={{ color: "var(--console-text-muted)", flexShrink: 0 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    fontSize: "0.8125rem",
                    fontWeight: 500,
                    color: "var(--console-text-primary)",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}>
                    {asset.title || t("study.assets.untitled")}
                  </div>
                  <div style={{ fontSize: "0.6875rem", color: "var(--console-text-muted)", marginTop: 2 }}>
                    {asset.asset_type} &middot; {t("study.assets.chunks", { count: asset.total_chunks })}
                  </div>
                </div>
                {STATUS_ICONS[asset.status] || null}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
