"use client";

import { useEffect, useState } from "react";
import { Database } from "lucide-react";
import { useTranslations } from "next-intl";
import { apiGet } from "@/lib/api";

interface StorageUsage {
  workspace_id: string;
  raw_bytes: number;
  version_bytes: number;
  reserved_bytes: number;
  total_bytes: number;
  quota_bytes: number;
  available_bytes: number;
  is_unlimited: boolean;
  is_over_quota: boolean;
}

const GB = 1024 * 1024 * 1024;
const MB = 1024 * 1024;

function formatBytes(bytes: number): string {
  if (bytes >= GB) return `${(bytes / GB).toFixed(2)} GB`;
  if (bytes >= MB) return `${(bytes / MB).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

/** Compact "used / quota" pill with color-coded fill bar.
 *
 * Hidden in unlimited mode (self-hosted defaults), pops to red when
 * the workspace is at >=90% of its quota so the user notices BEFORE
 * the upload-presign 402 hits them. */
export default function StorageUsageBadge() {
  const t = useTranslations("console-notebooks");
  const [usage, setUsage] = useState<StorageUsage | null>(null);

  useEffect(() => {
    let cancelled = false;
    void apiGet<StorageUsage>("/api/v1/workspaces/me/storage-usage")
      .then((data) => {
        if (!cancelled) setUsage(data);
      })
      .catch(() => {
        // Endpoint may not be reachable in some environments — silently
        // collapse the badge rather than surface a noisy error.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!usage || usage.is_unlimited) return null;

  const ratio = Math.min(1, usage.total_bytes / Math.max(1, usage.quota_bytes));
  const pct = Math.round(ratio * 100);
  const tone = usage.is_over_quota
    ? "danger"
    : ratio >= 0.9
      ? "warn"
      : "ok";

  return (
    <div
      className={`storage-usage-badge is-${tone}`}
      title={t("storage.tooltip", {
        raw: formatBytes(usage.raw_bytes),
        versions: formatBytes(usage.version_bytes),
      })}
      data-testid="storage-usage-badge"
    >
      <Database size={12} />
      <span className="storage-usage-badge__text">
        {formatBytes(usage.total_bytes)} / {formatBytes(usage.quota_bytes)}
      </span>
      <span
        className="storage-usage-badge__fill"
        style={{ width: `${pct}%` }}
        aria-hidden="true"
      />
    </div>
  );
}
