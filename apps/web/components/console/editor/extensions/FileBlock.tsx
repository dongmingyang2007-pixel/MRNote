"use client";

import { Node, mergeAttributes } from "@tiptap/core";
import type { NodeViewProps } from "@tiptap/react";
import { NodeViewWrapper, ReactNodeViewRenderer } from "@tiptap/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { FileUp, Loader2, Download, ExternalLink } from "lucide-react";
import { apiGet, apiPostFormData } from "@/lib/api";
import { useCurrentPageId } from "@/components/console/editor/PageIdContext";
import { useWindowManager } from "@/components/notebook/WindowManager";

interface FileBlockAttrs {
  attachment_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
}

function humanSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function FileBlockView(props: NodeViewProps) {
  const attrs = props.node.attrs as FileBlockAttrs;
  const hasAttachment = Boolean(attrs.attachment_id);

  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const pageId = useCurrentPageId();
  const { openWindow } = useWindowManager();

  useEffect(() => {
    if (!attrs.attachment_id) return;
    let cancelled = false;
    void apiGet<{ url: string }>(`/api/v1/attachments/${attrs.attachment_id}/url`)
      .then((r) => {
        if (!cancelled) setUrl(r.url);
      })
      .catch(() => {
        if (!cancelled) setUrl(null);
      });
    return () => {
      cancelled = true;
    };
  }, [attrs.attachment_id]);

  const handlePick = useCallback(() => inputRef.current?.click(), []);

  const handleOpenInWindow = useCallback(() => {
    if (!url) return;
    openWindow({
      type: "file",
      title: attrs.filename || "File",
      meta: {
        url,
        mimeType: attrs.mime_type,
        filename: attrs.filename,
      },
    });
  }, [openWindow, url, attrs.filename, attrs.mime_type]);

  const handleFile = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      if (!pageId) {
        setError("Page not ready yet, try again.");
        return;
      }
      setUploading(true);
      setError(null);
      try {
        const fd = new FormData();
        fd.append("file", file);
        const resp = await apiPostFormData<{
          attachment_id: string;
          filename: string;
          mime_type: string;
          size_bytes: number;
        }>(`/api/v1/pages/${pageId}/attachments/upload`, fd);
        props.updateAttributes({
          attachment_id: resp.attachment_id,
          filename: resp.filename,
          mime_type: resp.mime_type,
          size_bytes: resp.size_bytes,
        });
      } catch (err) {
        setError(err instanceof Error ? err.message : "Upload failed");
      } finally {
        setUploading(false);
      }
    },
    [props, pageId],
  );

  return (
    <NodeViewWrapper className="file-block" data-testid="file-block">
      {!hasAttachment && (
        <button
          type="button"
          onClick={handlePick}
          disabled={uploading}
          data-testid="file-block-upload"
          className="file-block__picker"
        >
          {uploading ? <Loader2 size={14} className="animate-spin" /> : <FileUp size={14} />}
          {uploading ? "Uploading…" : "Upload file"}
        </button>
      )}
      {hasAttachment && (
        <div className="file-block__meta">
          <FileUp size={16} />
          <span className="file-block__name">{attrs.filename}</span>
          <span className="file-block__size">{humanSize(attrs.size_bytes)}</span>
          {url && attrs.mime_type.startsWith("image/") && (
            <button
              type="button"
              onClick={handleOpenInWindow}
              className="file-block__image-button"
              title="Open in window"
              data-testid="file-block-open-image"
            >
              <img src={url} alt={attrs.filename} className="file-block__preview" />
            </button>
          )}
          {url && !attrs.mime_type.startsWith("image/") && (
            <button
              type="button"
              onClick={handleOpenInWindow}
              className="file-block__open"
              data-testid="file-block-open"
            >
              <ExternalLink size={14} /> Open
            </button>
          )}
          {url && (
            <a
              href={url}
              download={attrs.filename}
              className="file-block__download"
              title="Download"
            >
              <Download size={14} />
            </a>
          )}
        </div>
      )}
      {error && <p className="file-block__error">{error}</p>}
      <input
        ref={inputRef}
        type="file"
        style={{ display: "none" }}
        onChange={handleFile}
      />
    </NodeViewWrapper>
  );
}

const FileBlock = Node.create({
  name: "file",
  group: "block",
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      attachment_id: { default: "" },
      filename: { default: "" },
      mime_type: { default: "" },
      size_bytes: { default: 0 },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-type="file"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-type": "file" })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(FileBlockView);
  },
});

export default FileBlock;
