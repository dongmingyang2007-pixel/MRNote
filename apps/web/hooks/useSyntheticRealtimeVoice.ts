"use client";

import { useCallback, useRef, useState } from "react";
import {
  useRealtimeVoiceBase,
  type RealtimeState,
  type TranscriptEntry,
  type RealtimeVoiceBaseConfig,
} from "./useRealtimeVoiceBase";
import type { PersistedRealtimeMessage, PersistedRealtimeTurnPayload } from "./useRealtimeVoice";

export type SyntheticRealtimeState = RealtimeState;

export interface SyntheticPendingMedia {
  kind: "image" | "video";
  filename: string;
  mimeType: string;
  dataUrl: string;
}

interface UseSyntheticRealtimeVoiceOptions {
  conversationId: string;
  projectId: string;
  onError?: (msg: string) => void;
  onTurnComplete?: (payload: {
    userText: string;
    assistantText: string;
  }) => void;
  onTranscriptUpdate?: (payload: {
    role: "user" | "assistant";
    text: string;
    final: boolean;
    action?: "upsert" | "discard";
  }) => void;
  onTurnPersisted?: (payload: PersistedRealtimeTurnPayload) => void;
  messages?: RealtimeVoiceBaseConfig["messages"];
}

interface UseSyntheticRealtimeVoiceReturn {
  state: SyntheticRealtimeState;
  transcript: TranscriptEntry[];
  timer: number;
  connect: () => Promise<void>;
  disconnect: () => void;
  toggleMute: () => void;
  isMuted: boolean;
  toggleSpeakerMute: () => void;
  isSpeakerMuted: boolean;
  userVolume: number;
  aiVolume: number;
  sendJson: (data: Record<string, unknown>) => void;
  pendingMedia: SyntheticPendingMedia | null;
  attachMediaFile: (file: File) => Promise<void>;
  clearPendingMedia: () => void;
  turnBoundaryCount: number;
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("failed_to_read_file"));
    reader.readAsDataURL(file);
  });
}

export function useSyntheticRealtimeVoice({
  conversationId,
  projectId,
  onError,
  onTurnComplete,
  onTranscriptUpdate,
  onTurnPersisted,
  messages,
}: UseSyntheticRealtimeVoiceOptions): UseSyntheticRealtimeVoiceReturn {
  const [pendingMedia, setPendingMedia] = useState<SyntheticPendingMedia | null>(null);
  const [turnBoundaryCount, setTurnBoundaryCount] = useState(0);
  const pendingMediaRef = useRef<SyntheticPendingMedia | null>(null);
  const pendingMediaVersionRef = useRef(0);
  const lastSentMediaVersionRef = useRef(0);

  const sendPendingMedia = useCallback((ws: WebSocket) => {
    const media = pendingMediaRef.current;
    const version = pendingMediaVersionRef.current;
    if (!media || ws.readyState !== WebSocket.OPEN || version === lastSentMediaVersionRef.current) return;
    if (pendingMediaRef.current !== media || pendingMediaVersionRef.current !== version) {
      return;
    }
    ws.send(
      JSON.stringify({
        type: "media.set",
        data_url: media.dataUrl,
        filename: media.filename,
      }),
    );
    lastSentMediaVersionRef.current = version;
  }, []);

  const base = useRealtimeVoiceBase({
    conversationId,
    projectId,
    wsPath: "/api/v1/realtime/composed-voice",
    audioSendMode: "continuous",
    blockCaptureWhileAiSpeaking: true,
    enableInterrupt: true,
    interruptPendingResponse: false,
    vadConfig: {
      speechThreshold: 0.015,
      silenceCommitMs: 850,
    },
    onError,
    onTurnComplete: (payload) => {
      setTurnBoundaryCount((currentValue) => currentValue + 1);
      onTurnComplete?.(payload);
    },
    onTranscriptUpdate,
    messages,
    onSessionReady: sendPendingMedia,
    onCustomMessage: (data) => {
      if (data.type === "media.attached") {
        lastSentMediaVersionRef.current = pendingMediaVersionRef.current;
      } else if (data.type === "media.cleared") {
        setPendingMedia(null);
        pendingMediaRef.current = null;
      } else if (data.type === "turn.error") {
        setTurnBoundaryCount((currentValue) => currentValue + 1);
      } else if (data.type === "turn.notice") {
        const noticeCode = typeof data.code === "string" ? data.code : "";
        if (noticeCode === "empty_transcription" || noticeCode === "no_audio_input") {
          setTurnBoundaryCount((currentValue) => currentValue + 1);
        }
      } else if (data.type === "turn.persisted") {
        onTurnPersisted?.({
          userMessage:
            data.user_message && typeof data.user_message === "object"
              ? (data.user_message as PersistedRealtimeMessage)
              : undefined,
          assistantMessage:
            data.assistant_message && typeof data.assistant_message === "object"
              ? (data.assistant_message as PersistedRealtimeMessage)
              : undefined,
        });
      }
    },
  });

  const attachMediaFile = useCallback(
    async (file: File) => {
      const dataUrl = await readFileAsDataUrl(file);
      const nextMedia: SyntheticPendingMedia = {
        kind: file.type.startsWith("video/") ? "video" : "image",
        filename: file.name,
        mimeType:
          file.type || (file.name.toLowerCase().endsWith(".mp4") ? "video/mp4" : "image/jpeg"),
        dataUrl,
      };
      pendingMediaVersionRef.current += 1;
      pendingMediaRef.current = nextMedia;
      setPendingMedia(nextMedia);

      base.sendJson({
        type: "media.set",
        data_url: nextMedia.dataUrl,
        filename: nextMedia.filename,
      });
    },
    [base.sendJson],
  );

  const clearPendingMedia = useCallback(() => {
    pendingMediaVersionRef.current += 1;
    pendingMediaRef.current = null;
    setPendingMedia(null);
    base.sendJson({ type: "media.clear" });
  }, [base.sendJson]);

  return {
    state: base.state,
    transcript: base.transcript,
    timer: base.timer,
    connect: base.connect,
    disconnect: base.disconnect,
    toggleMute: base.toggleMute,
    isMuted: base.isMuted,
    toggleSpeakerMute: base.toggleSpeakerMute,
    isSpeakerMuted: base.isSpeakerMuted,
    userVolume: base.userVolume,
    aiVolume: base.aiVolume,
    sendJson: base.sendJson,
    pendingMedia,
    attachMediaFile,
    clearPendingMedia,
    turnBoundaryCount,
  };
}
