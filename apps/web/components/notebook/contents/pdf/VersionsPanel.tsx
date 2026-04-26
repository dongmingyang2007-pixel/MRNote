"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  History,
  Loader2,
  RefreshCcw,
  RotateCcw,
  X,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { apiGet, apiPost } from "@/lib/api";

interface VersionsPanelProps {
  open: boolean;
  dataItemId: string;
  onClose: () => void;
  onRestored?: () => void;
}

interface VersionItem {
  id: string;
  version: number;
  size_bytes: number;
  media_type: string;
  saved_via: string;
  saved_by: string | null;
  note: string | null;
  created_at: string | null;
}

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(value: string | null): string {
  if (!value) return "";
  try {
    return new Intl.DateTimeFormat(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(value));
  } catch {
    return value;
  }
}

export default function VersionsPanel({
  open,
  dataItemId,
  onClose,
  onRestored,
}: VersionsPanelProps) {
  const t = useTranslations("console-notebooks");
  const [versions, setVersions] = useState<VersionItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [restoring, setRestoring] = useState<string | null>(null);
  const [restoredId, setRestoredId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!dataItemId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await apiGet<VersionItem[]>(
        `/api/v1/data-items/${dataItemId}/versions`,
      );
      setVersions(data || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("references.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [dataItemId, t]);

  useEffect(() => {
    if (!open) return;
    setRestoredId(null);
    void load();
  }, [load, open]);

  const restore = useCallback(
    async (version: VersionItem) => {
      if (restoring) return;
      const confirmed = window.confirm(
        t("versions.restoreConfirm", { version: version.version }),
      );
      if (!confirmed) return;
      setRestoring(version.id);
      setError(null);
      try {
        await apiPost(
          `/api/v1/data-items/${dataItemId}/versions/${version.id}/restore`,
          {},
        );
        setRestoredId(version.id);
        onRestored?.();
        // Reload to surface the auto-snapshot the backend writes pre-restore.
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : t("versions.restoreFailed"));
      } finally {
        setRestoring(null);
      }
    },
    [dataItemId, load, onRestored, restoring, t],
  );

  if (!open) return null;

  return (
    <aside className="versions-panel" data-testid="versions-panel">
      <header>
        <strong>
          <History size={14} /> {t("versions.title")}
        </strong>
        <div className="versions-panel__actions">
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            title={t("versions.refresh")}
            aria-label={t("versions.refresh")}
          >
            {loading ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <RefreshCcw size={13} />
            )}
          </button>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("versions.close")}
          >
            <X size={14} />
          </button>
        </div>
      </header>

      {error ? (
        <div className="versions-panel__error">
          <AlertCircle size={14} />
          {error}
        </div>
      ) : null}

      <div className="versions-panel__body">
        {loading ? (
          <div className="versions-panel__empty">
            <Loader2 size={20} className="animate-spin" />
          </div>
        ) : versions.length === 0 ? (
          <div className="versions-panel__empty">
            <span>{t("versions.empty")}</span>
            <small>{t("versions.emptyHint")}</small>
          </div>
        ) : (
          <ul>
            {versions.map((v, idx) => (
              <li key={v.id}>
                <div className="versions-panel__row">
                  <div>
                    <strong>
                      {idx === 0 ? t("versions.current") : `v${v.version}`}
                    </strong>
                    <small>{formatDate(v.created_at)}</small>
                    <span>
                      {humanSize(v.size_bytes)} · {v.saved_via}
                    </span>
                    {v.note ? <em>{v.note}</em> : null}
                  </div>
                  {idx === 0 ? null : (
                    <button
                      type="button"
                      onClick={() => void restore(v)}
                      disabled={!!restoring}
                      data-testid="versions-panel-restore"
                    >
                      {restoring === v.id ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : restoredId === v.id ? (
                        <CheckCircle2 size={12} />
                      ) : (
                        <RotateCcw size={12} />
                      )}
                      {restoring === v.id
                        ? t("versions.restoring")
                        : restoredId === v.id
                          ? t("versions.restored")
                          : t("versions.restore")}
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}
