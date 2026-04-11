"use client";

import {
  useRealtimeVoiceBase,
  type RealtimeState,
  type TranscriptEntry,
  type RealtimeVoiceBaseReturn,
  type RealtimeVoiceBaseConfig,
} from "./useRealtimeVoiceBase";

export type { RealtimeState, TranscriptEntry };

export interface PersistedRealtimeMessage {
  id: string;
  conversation_id?: string;
  role: "user" | "assistant";
  content: string;
  reasoning_content?: string | null;
  metadata_json?: Record<string, unknown>;
  created_at?: string;
}

export interface PersistedRealtimeTurnPayload {
  userMessage?: PersistedRealtimeMessage;
  assistantMessage?: PersistedRealtimeMessage;
}

interface UseRealtimeVoiceOptions {
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

interface UseRealtimeVoiceReturn {
  state: RealtimeState;
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
}

export function useRealtimeVoice({
  conversationId,
  projectId,
  onError,
  onTurnComplete,
  onTranscriptUpdate,
  onTurnPersisted,
  messages,
}: UseRealtimeVoiceOptions): UseRealtimeVoiceReturn {
  const base: RealtimeVoiceBaseReturn = useRealtimeVoiceBase({
    conversationId,
    projectId,
    wsPath: "/api/v1/realtime/voice",
    audioSendMode: "continuous",
    enableInterrupt: true,
    vadConfig: {
      speechThreshold: 0.015,
      interruptThresholdMs: 400,
      speechCooldownMs: 200,
    },
    onError,
    onTurnComplete,
    onTranscriptUpdate,
    messages,
    onCustomMessage: (data) => {
      if (data.type !== "turn.persisted") {
        return;
      }
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
    },
  });

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
  };
}
