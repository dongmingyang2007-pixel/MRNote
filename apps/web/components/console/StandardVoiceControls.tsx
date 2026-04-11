"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { useRealtimeDictation } from "@/hooks/useRealtimeDictation";

export interface StandardVoiceControlsProps {
  conversationId: string;
  projectId: string;
  isTyping: boolean;
  disabled: boolean;
  onDictationDraftChange: (text: string) => void;
  onDictationStateChange: (active: boolean) => void;
  onError: (message: string) => void;
}

export function StandardVoiceControls({
  conversationId,
  projectId,
  isTyping,
  disabled,
  onDictationDraftChange,
  onDictationStateChange,
  onError,
}: StandardVoiceControlsProps) {
  const t = useTranslations("console-chat");
  const [asrAvailable, setAsrAvailable] = useState(true);
  const dictation = useRealtimeDictation({
    conversationId,
    projectId,
    onDraftChange: onDictationDraftChange,
    onError: (message) => {
      const friendlyMessage =
        message === "model_api_unconfigured" ? t("errors.modelUnconfigured") : message;
      if (message === "model_api_unconfigured") {
        setAsrAvailable(false);
      }
      onError(friendlyMessage);
    },
  });

  useEffect(() => {
    onDictationStateChange(dictation.isActive);
  }, [dictation.isActive, onDictationStateChange]);

  const handleMicClick = useCallback(async () => {
    if (dictation.isActive) {
      dictation.disconnect();
      return;
    }
    try {
      await dictation.connect();
    } catch {
      onError(t("micPermissionDenied"));
    }
  }, [dictation, onError, t]);

  if (!asrAvailable) return null;

  const isRecording = dictation.isActive;
  const isConnecting = dictation.state === "connecting" || dictation.state === "reconnecting";
  const statusText = isConnecting ? t("realtimePreparing") : t("voiceRecording");
  // Warm accent colors inherited from CSS custom properties (--voice-accent)

  return (
    <>
      <button
        className={`chat-mic-btn ${isRecording ? "is-recording" : ""}`}
        onClick={() => void handleMicClick()}
        disabled={(isTyping && !isRecording) || disabled}
        title={isRecording ? t("voiceRecording") : t("voiceRecord")}
        type="button"
      >
        {isRecording ? (
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <rect x="6" y="6" width="12" height="12" rx="2" />
          </svg>
        ) : (
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <rect x="9" y="2" width="6" height="12" rx="3" />
            <path d="M5 10a7 7 0 0 0 14 0" />
            <line x1="12" y1="19" x2="12" y2="22" />
          </svg>
        )}
      </button>

      {isRecording ? (
        <div className="chat-voice-indicator">{statusText}</div>
      ) : null}
    </>
  );
}
