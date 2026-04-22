"use client";

import { FileUp } from "lucide-react";
import { getSafeExternalUrl } from "@/lib/security";

interface FileWindowProps {
  url?: string;
  previewUrl?: string;
  downloadUrl?: string;
  mimeType?: string;
  filename?: string;
}

export default function FileWindow({
  url,
  previewUrl,
  downloadUrl,
  mimeType,
  filename,
}: FileWindowProps) {
  const safePreviewUrl = getSafeExternalUrl(previewUrl || url) || undefined;
  const safeDownloadUrl = getSafeExternalUrl(downloadUrl || safePreviewUrl || url) || undefined;

  const isPdf =
    Boolean(safePreviewUrl) &&
    (mimeType === "application/pdf" ||
      (filename && filename.toLowerCase().endsWith(".pdf")));

  const isImage = Boolean(safePreviewUrl) && mimeType?.startsWith("image/");

  if (!safePreviewUrl && !safeDownloadUrl) {
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          height: "100%",
          color: "var(--console-text-muted)",
          gap: 8,
        }}
      >
        <FileUp size={32} strokeWidth={1.5} style={{ opacity: 0.4 }} />
        <span style={{ fontSize: "0.875rem" }}>No file selected</span>
      </div>
    );
  }

  if (isPdf) {
    return (
      <iframe
        src={safePreviewUrl}
        style={{ width: "100%", height: "100%", border: "none" }}
        title={filename || "PDF viewer"}
      />
    );
  }

  if (isImage) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "100%",
          padding: 16,
          overflow: "auto",
        }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={safePreviewUrl}
          alt={filename || "File preview"}
          style={{ maxWidth: "100%", objectFit: "contain" }}
        />
      </div>
    );
  }

  // Default: filename with download link
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        height: "100%",
        gap: 12,
      }}
    >
      <FileUp size={40} strokeWidth={1.5} style={{ opacity: 0.4, color: "var(--console-text-muted)" }} />
      <span
        style={{
          fontSize: "0.875rem",
          fontWeight: 500,
          color: "var(--console-text-primary)",
        }}
      >
        {filename || "File"}
      </span>
      <a
        href={safeDownloadUrl}
        download={filename}
        style={{
          fontSize: "0.8125rem",
          color: "var(--console-accent, #2563EB)",
          textDecoration: "none",
        }}
      >
        Download
      </a>
    </div>
  );
}
