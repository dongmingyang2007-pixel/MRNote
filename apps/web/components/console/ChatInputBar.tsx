"use client";

import { useRef, useState, useCallback, useEffect } from "react";
import { useTranslations } from "next-intl";

import { appendNaturalText, cycleState } from "./chat-types";

type ToolGlyphName =
  | "plus"
  | "spark"
  | "read"
  | "image"
  | "upload"
  | "camera"
  | "search"
  | "think";

function ToolGlyph({
  name,
  className,
}: {
  name: ToolGlyphName;
  className?: string;
}) {
  const sharedProps = {
    className,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.9,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };

  switch (name) {
    case "plus":
      return (
        <svg {...sharedProps}>
          <path d="M12 4.4v15.2" />
          <path d="M4.6 12h14.8" />
          <path d="M7.2 6.9c.8-.6 1.5-.9 2.4-1" opacity={0.55} />
        </svg>
      );
    case "spark":
      return (
        <svg {...sharedProps}>
          <path d="M11.6 3.8c.2 1.9.8 3.5 1.8 4.8 1 1.3 2.4 2.2 4.1 2.8-1.7.4-3.1 1.2-4.2 2.5-1.1 1.3-1.7 3-1.9 5-.3-1.9-.9-3.4-1.9-4.7-1-1.2-2.5-2.1-4.3-2.7 1.7-.5 3.2-1.4 4.2-2.7 1.1-1.3 1.8-2.9 2.2-5Z" />
          <path d="M18.1 5.2v2.7" opacity={0.7} />
          <path d="M19.5 6.6h-2.8" opacity={0.7} />
        </svg>
      );
    case "read":
      return (
        <svg {...sharedProps}>
          <path d="M6 15V8.6c0-1 .7-1.7 1.7-1.7h3.3l3.2-2.4v14.8L11 16.9H7.7C6.7 16.9 6 16.2 6 15Z" />
          <path d="M16.7 9.1c1 .8 1.5 1.8 1.5 2.9 0 1.1-.5 2.1-1.5 2.9" />
          <path d="M18.8 7.3c1.5 1.3 2.3 2.9 2.3 4.7s-.8 3.4-2.3 4.7" opacity={0.65} />
        </svg>
      );
    case "image":
      return (
        <svg {...sharedProps}>
          <rect x="4.4" y="5.4" width="15.2" height="13.4" rx="3.2" />
          <path d="M7.4 15.8l3.3-3.4 2.7 2.5 2.2-2.2 1.9 3.1" />
          <circle cx="9.4" cy="9.4" r="1.3" />
        </svg>
      );
    case "upload":
      return (
        <svg {...sharedProps}>
          <path d="M12 16.9V6.6" />
          <path d="M8.5 10.1L12 6.5l3.5 3.6" />
          <path d="M6.1 18.5h11.8" />
          <path d="M7.2 4.6h9.4" opacity={0.5} />
        </svg>
      );
    case "camera":
      return (
        <svg {...sharedProps}>
          <path d="M6.4 8h2l1.1-1.9h4.9L15.6 8h2c1.1 0 2 .9 2 2v5.6c0 1.1-.9 2-2 2H6.4c-1.1 0-2-.9-2-2V10c0-1.1.9-2 2-2Z" />
          <circle cx="12" cy="12.8" r="3.1" />
          <path d="M18.1 9.1h.1" opacity={0.7} />
        </svg>
      );
    case "search":
      return (
        <svg {...sharedProps}>
          <circle cx="10.4" cy="10.3" r="4.6" />
          <path d="M13.8 13.8 19 19" />
          <path d="M8.2 10.1c.6-1.2 1.6-2.1 3-2.5" opacity={0.55} />
        </svg>
      );
    case "think":
      return (
        <svg {...sharedProps}>
          <path d="M8.1 15.9c-1.6-1.2-2.4-2.9-2.4-5 0-3.8 2.8-6.5 6.6-6.5 3.7 0 6.3 2.6 6.3 6.1 0 1.8-.7 3.3-2 4.6-.8.7-1.3 1.4-1.5 2.2H9.7c-.2-.8-.7-1.3-1.6-1.9Z" />
          <path d="M10 20h4" />
          <path d="M9.4 7.8c.7-.8 1.8-1.3 3.1-1.3 1 0 1.9.3 2.6.8" opacity={0.55} />
        </svg>
      );
    default:
      return null;
  }
}

export interface ChatInputBarProps {
  onSend: (
    content: string,
    options: {
      enableThinking?: boolean | null;
      enableSearch?: boolean | null;
      imageFile?: File | null;
    },
  ) => void;
  disabled: boolean;
  isTyping: boolean;
  isStandardMode: boolean;
  searchAvailable: boolean;
  autoReadEnabled: boolean;
  onAutoReadToggle: () => void;
  liveExternalInputText?: string | null;
  isLiveExternalInputActive?: boolean;
}

export function ChatInputBar({
  onSend,
  disabled,
  isTyping,
  isStandardMode,
  searchAvailable,
  autoReadEnabled,
  onAutoReadToggle,
  liveExternalInputText,
  isLiveExternalInputActive = false,
}: ChatInputBarProps) {
  const t = useTranslations("console-chat");
  const [input, setInput] = useState("");
  const [searchState, setSearchState] = useState<"auto" | "on" | "off">("auto");
  const [thinkState, setThinkState] = useState<"auto" | "on" | "off">("auto");
  const [pendingImageFile, setPendingImageFile] = useState<File | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [imageMenuOpen, setImageMenuOpen] = useState(false);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const imageUploadRef = useRef<HTMLInputElement>(null);
  const imageCaptureRef = useRef<HTMLInputElement>(null);
  const liveExternalBaseRef = useRef<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const effectiveSearchState = searchAvailable ? searchState : "auto";

  useEffect(() => {
    if (!isLiveExternalInputActive) {
      liveExternalBaseRef.current = null;
      return;
    }

    setInput((prev) => {
      const base = liveExternalBaseRef.current ?? prev;
      liveExternalBaseRef.current = base;
      const draft = liveExternalInputText || "";
      if (!draft) {
        return base;
      }
      return appendNaturalText(base, draft);
    });
    textareaRef.current?.focus();
  }, [isLiveExternalInputActive, liveExternalInputText]);

  useEffect(() => {
    if (!menuOpen) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) {
        setMenuOpen(false);
        setImageMenuOpen(false);
      }
    };

    window.addEventListener("mousedown", handlePointerDown);
    return () => window.removeEventListener("mousedown", handlePointerDown);
  }, [menuOpen]);

  const handleInput = useCallback(() => {
    const el = textareaRef.current;
    if (!el) {
      return;
    }
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, []);

  const handleImageFileSelected = useCallback((file: File | null) => {
    if (!file || !file.type.startsWith("image/")) {
      return;
    }
    setPendingImageFile(file);
  }, []);

  const clearPendingImage = useCallback(() => {
    setPendingImageFile(null);
  }, []);

  const handleSubmit = useCallback(() => {
    const text = input.trim();
    if (
      (!text && !pendingImageFile) ||
      isTyping ||
      disabled ||
      isLiveExternalInputActive
    ) {
      return;
    }

    const enableThinking =
      thinkState === "on" ? true : thinkState === "off" ? false : null;
    const enableSearch = !searchAvailable
      ? null
      : effectiveSearchState === "on"
        ? true
        : effectiveSearchState === "off"
          ? false
          : null;

    onSend(text, {
      enableThinking,
      enableSearch,
      imageFile: pendingImageFile,
    });

    setInput("");
    setPendingImageFile(null);
    setMenuOpen(false);
    setImageMenuOpen(false);
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [
    disabled,
    effectiveSearchState,
    input,
    isLiveExternalInputActive,
    isTyping,
    onSend,
    pendingImageFile,
    searchAvailable,
    thinkState,
  ]);

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSubmit();
    }
  };

  const activeTools = [
    isStandardMode && autoReadEnabled
      ? {
          key: "auto-read",
          label: t("activeTool.autoRead"),
          icon: "read" as ToolGlyphName,
          onRemove: onAutoReadToggle,
        }
      : null,
    searchAvailable && effectiveSearchState === "on"
      ? {
          key: "search",
          label: t("activeTool.search"),
          icon: "search" as ToolGlyphName,
          onRemove: () => setSearchState("auto"),
        }
      : null,
    thinkState === "on"
      ? {
          key: "think",
          label: t("activeTool.think"),
          icon: "think" as ToolGlyphName,
          onRemove: () => setThinkState("auto"),
        }
      : null,
    isStandardMode && pendingImageFile
      ? {
          key: "image",
          label: t("activeTool.image"),
          icon: "image" as ToolGlyphName,
          onRemove: clearPendingImage,
        }
      : null,
  ].filter(
    (
      item,
    ): item is {
      key: string;
      label: string;
      icon: ToolGlyphName;
      onRemove: () => void;
    } => item !== null,
  );
  const menuSummary = activeTools.length
    ? activeTools.map((tool) => tool.label).join(" · ")
    : t("toolMenuHint");

  const stateLabel = (state: "auto" | "on" | "off") => {
    if (state === "on") {
      return t("toolState.on");
    }
    if (state === "off") {
      return t("toolState.off");
    }
    return t("toolState.auto");
  };

  return (
    <>
      <input
        ref={imageUploadRef}
        type="file"
        accept="image/*"
        className="hidden"
        disabled={isTyping || disabled}
        data-testid="chat-image-upload-input"
        onChange={(event) => {
          handleImageFileSelected(event.target.files?.[0] || null);
          event.target.value = "";
        }}
      />
      <input
        ref={imageCaptureRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        disabled={isTyping || disabled}
        data-testid="chat-image-capture-input"
        onChange={(event) => {
          handleImageFileSelected(event.target.files?.[0] || null);
          event.target.value = "";
        }}
      />
      <div className="chat-input-bar">
        <div className="chat-input-shell">
          {activeTools.length ? (
            <div className="chat-active-tools" aria-label={t("toolsLabel")}>
              {activeTools.map((tool) => (
                <button
                  key={tool.key}
                  type="button"
                  className="chat-active-tool"
                  data-tool={tool.key}
                  onClick={tool.onRemove}
                >
                  <span className="chat-active-tool-icon">
                    <ToolGlyph name={tool.icon} />
                  </span>
                  <span>{tool.label}</span>
                  <span className="chat-active-tool-dismiss"><svg width={10} height={10} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round"><path d="M18 6 6 18M6 6l12 12" /></svg></span>
                </button>
              ))}
            </div>
          ) : null}

          <div className="chat-input-container">
            <textarea
              ref={textareaRef}
              className="chat-input-textarea"
              value={input}
              onChange={(event) => {
                setInput(event.target.value);
                handleInput();
              }}
              onKeyDown={handleKeyDown}
              placeholder={t("inputPlaceholder")}
              aria-label={t("inputPlaceholder")}
              rows={1}
              disabled={isTyping || disabled || isLiveExternalInputActive}
            />

            {isStandardMode && pendingImageFile ? (
              <div className="chat-attachment-chip">
                <span className="chat-attachment-name">
                  {pendingImageFile.name}
                </span>
                <button
                  type="button"
                  className="chat-audio-btn"
                  onClick={clearPendingImage}
                  aria-label={t("imageClear")}
                  style={{ cursor: "pointer" }}
                >
                  {t("imageClear")}
                </button>
              </div>
            ) : null}

            <div className="chat-input-toolbar">
              <div
                className="chat-input-toolbar-group chat-input-toolbar-group--utilities"
                ref={menuRef}
              >
                <button
                  type="button"
                  className={`chat-tools-trigger${menuOpen ? " is-open" : ""}`}
                  onClick={() => setMenuOpen((current) => !current)}
                  disabled={disabled || isLiveExternalInputActive}
                  aria-expanded={menuOpen}
                  aria-haspopup="menu"
                >
                  <span className="chat-tools-trigger-glyph">
                    <ToolGlyph name="plus" />
                  </span>
                  <span className="chat-tools-trigger-label">
                    {t("toolsLabel")}
                  </span>
                  <span className="chat-tools-trigger-spark">
                    <ToolGlyph name="spark" />
                  </span>
                </button>

                {menuOpen ? (
                  <div className="chat-tools-menu" role="menu">
                    <div className="chat-tools-menu-header">
                      <div className="chat-tools-menu-copy">
                        <span className="chat-tools-menu-kicker">
                          {t("toolsLabel")}
                        </span>
                        <span className="chat-tools-menu-summary">
                          {menuSummary}
                        </span>
                      </div>
                      <span className="chat-tools-menu-doodle">
                        <ToolGlyph name="spark" />
                      </span>
                    </div>

                    {isStandardMode ? (
                      <button
                        type="button"
                        className={`chat-tools-menu-item${autoReadEnabled ? " is-active" : ""}`}
                        role="menuitem"
                        onClick={() => {
                          onAutoReadToggle();
                          setMenuOpen(false);
                        }}
                      >
                        <span className="chat-tools-menu-item-body">
                          <span className="chat-tools-menu-item-icon">
                            <ToolGlyph name="read" />
                          </span>
                          <span className="chat-tools-menu-item-label">
                            {t("voiceAutoRead")}
                          </span>
                        </span>
                        <span
                          className="chat-tools-menu-item-state"
                          data-state={autoReadEnabled ? "on" : "off"}
                        >
                          {autoReadEnabled ? t("toolState.on") : t("toolState.off")}
                        </span>
                      </button>
                    ) : null}

                    {isStandardMode ? (
                      <div className="chat-tools-menu-group">
                        <button
                          type="button"
                          className={`chat-tools-menu-item${imageMenuOpen ? " is-active" : ""}`}
                          role="menuitem"
                          onClick={() => setImageMenuOpen((current) => !current)}
                          disabled={
                            isTyping || disabled || isLiveExternalInputActive
                          }
                        >
                          <span className="chat-tools-menu-item-body">
                            <span className="chat-tools-menu-item-icon">
                              <ToolGlyph name="image" />
                            </span>
                            <span className="chat-tools-menu-item-label">
                              {t("tool.addImage")}
                            </span>
                          </span>
                          <span
                            className="chat-tools-menu-item-state"
                            data-state={imageMenuOpen ? "on" : "auto"}
                          >
                            {imageMenuOpen ? (
                              <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round"><path d="M5 12h14" /></svg>
                            ) : (
                              <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>
                            )}
                          </span>
                        </button>
                        {imageMenuOpen ? (
                          <div className="chat-tools-submenu">
                            <button
                              type="button"
                              className="chat-tools-menu-item is-subitem"
                              role="menuitem"
                              aria-label={t("imageUpload")}
                              onClick={() => {
                                imageUploadRef.current?.click();
                                setMenuOpen(false);
                                setImageMenuOpen(false);
                              }}
                            >
                              <span className="chat-tools-menu-item-body">
                                <span className="chat-tools-menu-item-icon is-subitem">
                                  <ToolGlyph name="upload" />
                                </span>
                                <span className="chat-tools-menu-item-label">
                                  {t("imageUpload")}
                                </span>
                              </span>
                            </button>
                            <button
                              type="button"
                              className="chat-tools-menu-item is-subitem"
                              role="menuitem"
                              aria-label={t("imageCapture")}
                              onClick={() => {
                                imageCaptureRef.current?.click();
                                setMenuOpen(false);
                                setImageMenuOpen(false);
                              }}
                            >
                              <span className="chat-tools-menu-item-body">
                                <span className="chat-tools-menu-item-icon is-subitem">
                                  <ToolGlyph name="camera" />
                                </span>
                                <span className="chat-tools-menu-item-label">
                                  {t("imageCapture")}
                                </span>
                              </span>
                            </button>
                          </div>
                        ) : null}
                      </div>
                    ) : null}

                    {searchAvailable ? (
                      <button
                        type="button"
                        className={`chat-tools-menu-item${effectiveSearchState === "on" ? " is-active" : ""}`}
                        role="menuitem"
                        onClick={() =>
                          setSearchState((current) => cycleState(current))
                        }
                      >
                        <span className="chat-tools-menu-item-body">
                          <span className="chat-tools-menu-item-icon">
                            <ToolGlyph name="search" />
                          </span>
                          <span className="chat-tools-menu-item-label">
                            {t("tool.searchExpanded")}
                          </span>
                        </span>
                        <span
                          className="chat-tools-menu-item-state"
                          data-state={effectiveSearchState}
                        >
                          {stateLabel(effectiveSearchState)}
                        </span>
                      </button>
                    ) : null}

                    <button
                      type="button"
                      className={`chat-tools-menu-item${thinkState === "on" ? " is-active" : ""}`}
                      role="menuitem"
                      onClick={() =>
                        setThinkState((current) => cycleState(current))
                      }
                    >
                      <span className="chat-tools-menu-item-body">
                        <span className="chat-tools-menu-item-icon">
                          <ToolGlyph name="think" />
                        </span>
                        <span className="chat-tools-menu-item-label">
                          {t("tool.thinkExpanded")}
                        </span>
                      </span>
                      <span
                        className="chat-tools-menu-item-state"
                        data-state={thinkState}
                      >
                        {stateLabel(thinkState)}
                      </span>
                    </button>
                  </div>
                ) : null}
              </div>

              <div className="chat-input-toolbar-group chat-input-toolbar-group--send">
                <button
                  type="button"
                  className={`chat-input-send${input.trim() || pendingImageFile ? " has-content" : ""}`}
                  onClick={handleSubmit}
                  disabled={
                    (!input.trim() && !pendingImageFile) ||
                    isTyping ||
                    disabled ||
                    isLiveExternalInputActive
                  }
                >
                  <span>{t("send")}</span>
                  <svg
                    width={14}
                    height={14}
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={2}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M5 12h14" />
                    <path d="m12 5 7 7-7 7" />
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
