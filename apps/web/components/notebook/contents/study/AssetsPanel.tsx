"use client";

import { useCallback, useEffect, useState } from "react";
import { BookOpen, Loader2, CheckCircle, AlertCircle, FileText } from "lucide-react";
import { useTranslations } from "next-intl";

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
      const res = await fetch(`/api/v1/notebooks/${notebookId}/study`);
      if (res.ok) {
        const data = await res.json();
        setAssets(data.items || []);
      }
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
      const res = await fetch(`/api/v1/notebooks/${notebookId}/study/${assetId}/chunks?limit=50`);
      if (res.ok) {
        const data = await res.json();
        setChunks(data.items || []);
      }
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
      }}>
        <span style={{
          fontSize: "0.875rem",
          fontWeight: 600,
          color: "var(--console-text-primary)",
        }}>
          {t("study.assets.title")}
        </span>
      </div>

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
