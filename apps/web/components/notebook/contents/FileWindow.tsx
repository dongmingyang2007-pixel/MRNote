"use client";

import { FileUp } from "lucide-react";

interface FileWindowProps {
  url?: string;
  mimeType?: string;
  filename?: string;
}

function isSafeUrl(u: string): boolean {
  try {
    const parsed = new URL(u, window.location.origin);
    return ["https:", "http:", "blob:"].includes(parsed.protocol);
  } catch {
    return false;
  }
}

export default function FileWindow({ url, mimeType, filename }: FileWindowProps) {
  const isPdf =
    mimeType === "application/pdf" ||
    (filename && filename.toLowerCase().endsWith(".pdf"));

  const isImage = mimeType?.startsWith("image/");

  const safeUrl = url && isSafeUrl(url) ? url : undefined;

  if (!safeUrl) {
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
        src={safeUrl}
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
          src={safeUrl}
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
        href={safeUrl}
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
