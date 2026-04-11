"use client";

import { useTranslations } from "next-intl";

import type { ChatMode } from "./chat-types";

export interface ChatModePanelProps {
  chatMode: ChatMode;
  projectDefaultMode: ChatMode;
  syntheticModeAvailable: boolean;
  onModeChange: (mode: ChatMode) => void;
  disabled: boolean;
}

export function ChatModePanel({
  chatMode,
  projectDefaultMode,
  syntheticModeAvailable,
  onModeChange,
  disabled,
}: ChatModePanelProps) {
  const t = useTranslations("console-chat");
  const options = [
    { key: "standard", label: t("mode.standard") },
    { key: "omni_realtime", label: t("mode.omni") },
    { key: "synthetic_realtime", label: t("mode.synthetic") },
  ];
  const helperText =
    chatMode === "standard"
      ? t("mode.helper.standard")
      : chatMode === "omni_realtime"
        ? t("mode.helper.omni")
        : t("mode.helper.synthetic");

  return (
    <div className="chat-mode-switcher" aria-label={t("title")}>
      <div className="chat-mode-switcher-main">
        <div
          className="chat-mode-chip-group"
          role="tablist"
          aria-label={t("title")}
        >
          {options.map((option) => {
            const isDisabled =
              disabled ||
              (option.key === "synthetic_realtime" && !syntheticModeAvailable);
            const isActive = chatMode === option.key;

            return (
              <button
                key={option.key}
                type="button"
                className={`chat-mode-chip${isActive ? " is-active" : ""}`}
                onClick={() => onModeChange(option.key as ChatMode)}
                disabled={isDisabled}
                aria-pressed={isActive}
              >
                <span>{option.label}</span>
                {option.key === projectDefaultMode ? (
                  <span className="chat-mode-chip-default">
                    {t("mode.default")}
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
        <select
          className="chat-mode-dropdown"
          value={chatMode}
          disabled={disabled}
          aria-label={t("title")}
          onChange={(e) => onModeChange(e.target.value as ChatMode)}
        >
          {options.map((option) => (
            <option
              key={option.key}
              value={option.key}
              disabled={
                option.key === "synthetic_realtime" && !syntheticModeAvailable
              }
            >
              {option.label}
              {option.key === projectDefaultMode
                ? ` (${t("mode.default")})`
                : ""}
            </option>
          ))}
        </select>
      </div>
      <p className="chat-mode-helper">{helperText}</p>
    </div>
  );
}
