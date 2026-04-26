"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, Loader2, RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";
import { apiGet } from "@/lib/api";

interface OnlyOfficeEditorProps {
  dataItemId: string;
  onSaved?: () => void;
  onError?: (message: string) => void;
}

interface OnlyOfficeConfig {
  document: {
    fileType: string;
    key: string;
    title: string;
    url: string;
    permissions?: Record<string, boolean>;
  };
  documentType: "word" | "cell" | "slide";
  editorConfig: {
    callbackUrl: string;
    lang?: string;
    mode?: "edit" | "view";
    user?: { id: string; name: string };
    customization?: Record<string, unknown>;
  };
  token: string;
  type?: string;
  docServerUrl?: string;
}

interface DocsApiEditor {
  destroyEditor: () => void;
  refreshHistory?: (history: unknown) => void;
}

interface DocsApiCtor {
  DocEditor: new (
    placeholderId: string,
    config: Record<string, unknown>,
  ) => DocsApiEditor;
}

declare global {
  interface Window {
    DocsAPI?: DocsApiCtor;
  }
}

// Module-scoped script-load promise so multiple editor instances share one
// `<script>` injection. ONLYOFFICE's api.js attaches `window.DocsAPI` as a
// side effect; loading it twice causes warnings.
let onlyOfficeScriptPromise: Promise<void> | null = null;

function loadOnlyOfficeScript(serverUrl: string): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("Cannot load ONLYOFFICE script on server"));
  }
  if (window.DocsAPI) return Promise.resolve();
  if (onlyOfficeScriptPromise) return onlyOfficeScriptPromise;

  onlyOfficeScriptPromise = new Promise<void>((resolve, reject) => {
    const src = `${serverUrl.replace(/\/$/, "")}/web-apps/apps/api/documents/api.js`;
    const existing = document.querySelector<HTMLScriptElement>(
      `script[data-onlyoffice-loader="${src}"]`,
    );
    if (existing) {
      if (window.DocsAPI) {
        resolve();
        return;
      }
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener(
        "error",
        () => reject(new Error("ONLYOFFICE script failed to load")),
        { once: true },
      );
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.dataset.onlyofficeLoader = src;
    script.addEventListener(
      "load",
      () => {
        if (window.DocsAPI) resolve();
        else reject(new Error("ONLYOFFICE DocsAPI did not initialize"));
      },
      { once: true },
    );
    script.addEventListener(
      "error",
      () => {
        // Reset so a future retry can re-inject.
        onlyOfficeScriptPromise = null;
        reject(new Error("ONLYOFFICE script failed to load"));
      },
      { once: true },
    );
    document.head.appendChild(script);
  });
  return onlyOfficeScriptPromise;
}

type EditorState =
  | { kind: "loading" }
  | { kind: "disabled"; reason: "feature" | "config" }
  | { kind: "error"; message: string }
  | { kind: "ready"; config: OnlyOfficeConfig };

const DEFAULT_DOC_SERVER_URL =
  process.env.NEXT_PUBLIC_ONLYOFFICE_DOC_SERVER_URL || "";

export default function OnlyOfficeEditor({
  dataItemId,
  onSaved,
  onError,
}: OnlyOfficeEditorProps) {
  const t = useTranslations("console-notebooks");
  const [state, setState] = useState<EditorState>({ kind: "loading" });
  const containerRef = useRef<HTMLDivElement | null>(null);
  const editorRef = useRef<DocsApiEditor | null>(null);
  const placeholderId = `onlyoffice-editor-${dataItemId}`;

  const fetchConfig = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      const config = await apiGet<OnlyOfficeConfig>(
        `/api/v1/onlyoffice/documents/${dataItemId}/config`,
      );
      const serverUrl = config.docServerUrl || DEFAULT_DOC_SERVER_URL;
      if (!serverUrl) {
        setState({ kind: "disabled", reason: "config" });
        return;
      }
      // Cache the resolved URL on the config so the mount effect uses it.
      setState({
        kind: "ready",
        config: { ...config, docServerUrl: serverUrl },
      });
    } catch (err) {
      const message =
        err instanceof Error ? err.message : t("office.loadFailed");
      // 503 from backend means feature flag off — surface a softer state.
      if (/onlyoffice_disabled/i.test(message)) {
        setState({ kind: "disabled", reason: "feature" });
        return;
      }
      setState({ kind: "error", message });
    }
  }, [dataItemId, t]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      void fetchConfig();
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, [fetchConfig]);

  useEffect(() => {
    if (state.kind !== "ready") return;
    const config = state.config;
    const serverUrl = config.docServerUrl || DEFAULT_DOC_SERVER_URL;
    if (!serverUrl) return;
    let cancelled = false;

    void (async () => {
      try {
        await loadOnlyOfficeScript(serverUrl);
      } catch (err) {
        if (!cancelled) {
          const message =
            err instanceof Error ? err.message : t("office.loadFailed");
          setState({ kind: "error", message });
          onError?.(message);
        }
        return;
      }
      if (cancelled) return;
      if (!window.DocsAPI) return;
      if (!containerRef.current) return;

      // Build the runtime config for DocsAPI. Strip our private
      // `docServerUrl` field — ONLYOFFICE doesn't expect it.
      const runtimeConfig: Record<string, unknown> = { ...config };
      delete runtimeConfig.docServerUrl;

      const editorConfig = {
        ...runtimeConfig,
        events: {
          onError: (event: { data?: { errorCode?: number; errorDescription?: string } }) => {
            const message =
              event?.data?.errorDescription || t("office.loadFailed");
            onError?.(message);
          },
          onWarning: (event: unknown) => {
            console.warn("[onlyoffice] warning", event);
          },
          // onSave is not consistently fired across versions — use
          // onDocumentStateChange's `data===false` (no unsaved changes)
          // as the "saved" signal.
          onDocumentStateChange: (event: { data?: boolean }) => {
            if (event?.data === false) onSaved?.();
          },
          onRequestClose: () => {
            // Editor requests close — host window manager handles this.
          },
        },
      } as Record<string, unknown>;

      try {
        editorRef.current = new window.DocsAPI.DocEditor(
          placeholderId,
          editorConfig,
        );
      } catch (err) {
        const message =
          err instanceof Error ? err.message : t("office.loadFailed");
        setState({ kind: "error", message });
        onError?.(message);
      }
    })();

    return () => {
      cancelled = true;
      // Caveat: if the user closes the window mid-edit, ONLYOFFICE's
      // destroyEditor flush isn't guaranteed to persist unsaved changes.
      // ONLYOFFICE's autosave + force_save mitigate but don't eliminate this.
      try {
        editorRef.current?.destroyEditor();
      } catch {
        /* ignore */
      }
      editorRef.current = null;
    };
  }, [onError, onSaved, placeholderId, state, t]);

  if (state.kind === "loading") {
    return (
      <div className="onlyoffice-editor onlyoffice-editor--center">
        <Loader2 size={24} className="animate-spin" />
        <span>{t("office.loading")}</span>
      </div>
    );
  }

  if (state.kind === "disabled") {
    return (
      <div className="onlyoffice-editor onlyoffice-editor--center">
        <AlertCircle size={28} />
        <strong>{t("office.disabled")}</strong>
        <span>{t("office.disabledHint")}</span>
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="onlyoffice-editor onlyoffice-editor--center">
        <AlertCircle size={28} />
        <strong>{t("office.loadFailed")}</strong>
        <span>{state.message}</span>
        <button type="button" onClick={() => void fetchConfig()}>
          <RefreshCw size={14} />
          {t("office.retry")}
        </button>
      </div>
    );
  }

  return (
    <div className="onlyoffice-editor" ref={containerRef}>
      <div id={placeholderId} className="onlyoffice-editor__frame" />
    </div>
  );
}
