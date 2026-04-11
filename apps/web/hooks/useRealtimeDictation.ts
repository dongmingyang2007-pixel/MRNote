"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  useRealtimeVoiceBase,
  type RealtimeState,
  type RealtimeVoiceBaseReturn,
} from "./useRealtimeVoiceBase";
import { joinNaturalText } from "@/components/console/chat-types";

interface UseRealtimeDictationOptions {
  conversationId: string;
  projectId: string;
  onError?: (msg: string) => void;
  onDraftChange?: (text: string) => void;
}

interface UseRealtimeDictationReturn {
  state: RealtimeState;
  draftText: string;
  isActive: boolean;
  connect: () => Promise<void>;
  disconnect: () => void;
}

const ACTIVE_STATES = new Set<RealtimeState>([
  "connecting",
  "ready",
  "listening",
  "reconnecting",
]);

function joinSegments(finalSegments: string[], partial: string): string {
  const parts = [...finalSegments];
  const normalizedPartial = partial.trim();
  if (normalizedPartial) {
    parts.push(normalizedPartial);
  }
  return joinNaturalText(parts);
}

export function useRealtimeDictation({
  conversationId,
  projectId,
  onError,
  onDraftChange,
}: UseRealtimeDictationOptions): UseRealtimeDictationReturn {
  const [draftText, setDraftText] = useState("");
  const finalSegmentsRef = useRef<string[]>([]);
  const partialRef = useRef("");
  const pendingStopRef = useRef(false);
  const stopTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const publishDraft = useCallback(() => {
    const next = joinSegments(finalSegmentsRef.current, partialRef.current);
    setDraftText(next);
    onDraftChange?.(next);
  }, [onDraftChange]);

  const resetDraft = useCallback(() => {
    finalSegmentsRef.current = [];
    partialRef.current = "";
    setDraftText("");
    onDraftChange?.("");
  }, [onDraftChange]);

  const base: RealtimeVoiceBaseReturn = useRealtimeVoiceBase({
    conversationId,
    projectId,
    wsPath: "/api/v1/realtime/dictate",
    audioSendMode: "continuous",
    audioChunkSamples: 1024,
    enableInterrupt: false,
    vadConfig: {
      speechThreshold: 0.015,
    },
    onError,
    onTranscriptUpdate: ({ role, text, final }) => {
      if (role !== "user") {
        return;
      }
      if (final) {
        partialRef.current = "";
        const normalized = text.trim();
        if (normalized) {
          finalSegmentsRef.current.push(normalized);
        }
        if (pendingStopRef.current) {
          pendingStopRef.current = false;
          if (stopTimeoutRef.current) {
            clearTimeout(stopTimeoutRef.current);
            stopTimeoutRef.current = null;
          }
          base.disconnect();
        }
      } else {
        partialRef.current = text;
      }
      publishDraft();
    },
  });

  useEffect(() => {
    if (base.state === "idle" || base.state === "error") {
      partialRef.current = "";
      pendingStopRef.current = false;
      if (stopTimeoutRef.current) {
        clearTimeout(stopTimeoutRef.current);
        stopTimeoutRef.current = null;
      }
    }
  }, [base.state]);

  useEffect(() => {
    return () => {
      if (stopTimeoutRef.current) {
        clearTimeout(stopTimeoutRef.current);
        stopTimeoutRef.current = null;
      }
    };
  }, []);

  const connect = useCallback(async () => {
    resetDraft();
    await base.connect();
  }, [base, resetDraft]);

  const disconnect = useCallback(() => {
    pendingStopRef.current = true;
    base.sendJson({ type: "audio.stop" });
    if (stopTimeoutRef.current) {
      clearTimeout(stopTimeoutRef.current);
    }
    stopTimeoutRef.current = setTimeout(() => {
      stopTimeoutRef.current = null;
      if (pendingStopRef.current) {
        pendingStopRef.current = false;
        base.disconnect();
      }
    }, 800);
  }, [base]);

  const isActive = useMemo(() => ACTIVE_STATES.has(base.state), [base.state]);

  return {
    state: base.state,
    draftText,
    isActive,
    connect,
    disconnect,
  };
}
