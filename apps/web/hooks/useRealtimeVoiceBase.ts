"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, isApiRequestError } from "@/lib/api";
import { getApiBaseUrl } from "@/lib/env";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export type RealtimeState =
  | "idle"
  | "connecting"
  | "ready"
  | "listening"
  | "ai_speaking"
  | "error"
  | "reconnecting";

export interface TranscriptEntry {
  role: "user" | "assistant";
  text: string;
  final: boolean;
}

export interface RealtimeVoiceBaseConfig {
  conversationId: string;
  projectId: string;
  /** WebSocket path appended to the API host. */
  wsPath: string;
  /** Extra fields merged into the session.start payload. */
  sessionStartPayload?: Record<string, unknown>;
  /** "continuous" sends all PCM; "vad-gated" sends only during speech. */
  audioSendMode: "continuous" | "vad-gated";
  /** Browser-side PCM chunk size in samples. Smaller values reduce ASR latency. */
  audioChunkSamples?: number;
  vadConfig: {
    speechThreshold: number | "auto";
    interruptThresholdMs?: number;
    silenceCommitMs?: number;
    speechCooldownMs?: number;
  };
  /** Half-duplex safety: suppress microphone capture while AI audio is actively playing. */
  blockCaptureWhileAiSpeaking?: boolean;
  enableInterrupt: boolean;
  /** Whether user speech may interrupt a reply that is pending but has not started playing yet. */
  interruptPendingResponse?: boolean;
  /** Called immediately before sending `audio.stop` in VAD-gated mode. */
  beforeAudioStop?: () => Promise<void> | void;
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
  onStateChange?: (state: RealtimeState) => void;
  /** Called for WS message types not handled by the base. */
  onCustomMessage?: (data: Record<string, unknown>, ws: WebSocket) => void;
  /** Called after session.ready and before startCapture. */
  onSessionReady?: (ws: WebSocket) => void;
  /** Localized fallback strings for browser/runtime notices. */
  messages?: {
    autoplayBlocked?: string;
    microphonePermissionRequired?: string;
    websocketConnectionFailed?: string;
    turnError?: string;
    turnNotice?: string;
  };
}

export interface RealtimeVoiceBaseReturn {
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
  sendBinary: (data: ArrayBuffer) => void;
}

interface RealtimeWsTicketResponse {
  ticket: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_RECONNECT_ATTEMPTS = 3;
const CALIBRATION_DURATION_MS = 2000;
const CALIBRATION_MIN_THRESHOLD = 0.008;
const CALIBRATION_P75_MULTIPLIER = 2.5;
const SILENT_AUDIO_DATA_URL =
  "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";
const AUTOPLAY_BLOCKED_MESSAGE =
  "浏览器阻止了合成语音自动播放，请再次点击合成实时或检查静音设置";
const MICROPHONE_PERMISSION_REQUIRED_MESSAGE =
  "Microphone permission is required";
const WEBSOCKET_CONNECTION_FAILED_MESSAGE = "WebSocket connection failed";

// ---------------------------------------------------------------------------
// Playback strategy types (PCM via AudioContext  vs  Blob URL queue)
// ---------------------------------------------------------------------------

/** Detect whether the composed-voice (Blob/HTMLAudioElement) path should be used.
 *  Heuristic: composed-voice endpoint returns encoded audio (mp3), while the
 *  native realtime endpoint returns raw PCM at 24 kHz. The wsPath decides. */
function useBlobPlayback(wsPath: string): boolean {
  return wsPath.includes("composed");
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useRealtimeVoiceBase(
  config: RealtimeVoiceBaseConfig,
): RealtimeVoiceBaseReturn {
  // -- Keep a ref so WS callbacks always read the latest config ---------------
  const configRef = useRef(config);
  configRef.current = config;

  const { conversationId, projectId, wsPath } = config;

  const blobPlayback = useBlobPlayback(wsPath);

  // -- React state ------------------------------------------------------------
  const [state, setState] = useState<RealtimeState>("idle");
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [timer, setTimer] = useState(0);
  const [isMuted, setIsMuted] = useState(false);
  const isMutedRef = useRef(false);
  const [isSpeakerMuted, setIsSpeakerMuted] = useState(false);
  const isSpeakerMutedRef = useRef(false);
  const [userVolume, setUserVolume] = useState(0);
  const [aiVolume, setAiVolume] = useState(0);

  // -- Refs (WebSocket / audio / reconnect / state tracking) ------------------
  const wsRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const monitorGainRef = useRef<GainNode | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number>(0);

  // PCM playback refs (native realtime)
  const playbackCtxRef = useRef<AudioContext | null>(null);
  const playbackGainRef = useRef<GainNode | null>(null);
  const nextPlayTimeRef = useRef<number>(0);
  const playbackSourcesRef = useRef<AudioBufferSourceNode[]>([]);

  // Blob/HTMLAudioElement playback refs (composed realtime)
  const audioPlayerRef = useRef<HTMLAudioElement | null>(null);
  const playbackQueueRef = useRef<string[]>([]);
  const activePlaybackUrlRef = useRef<string | null>(null);
  const aiVolumeTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const playbackTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isPlaybackActiveRef = useRef(false);
  const pumpPlaybackQueueRef = useRef<() => void>(() => undefined);
  const audioMimeRef = useRef<string>("audio/mpeg");
  const blobPlaybackPrimedRef = useRef(false);
  const autoplayBlockedNoticeShownRef = useRef(false);

  // Reconnect / session
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const reconnectAttemptsRef = useRef(0);
  const manualDisconnectRef = useRef(false);
  const terminalErrorMessageRef = useRef<string | null>(null);
  const sessionEndReasonRef = useRef<string | null>(null);
  const currentUserTextRef = useRef("");
  const currentAssistantTextRef = useRef("");
  const openConnectionRef = useRef<
    (mode: "connect" | "reconnect") => Promise<void>
  >(() => Promise.resolve());
  const sessionContextRef = useRef(`${projectId}:${conversationId}`);

  const getMessage = useCallback(
    (
      key: keyof NonNullable<RealtimeVoiceBaseConfig["messages"]>,
      fallback: string,
    ) => configRef.current.messages?.[key] || fallback,
    [],
  );

  // VAD refs (used in vad-gated mode)
  const speechActiveRef = useRef(false);
  const lastSpeechAtRef = useRef(0);
  const hasSegmentAudioRef = useRef(false);

  // Interrupt tracking
  const interruptStartRef = useRef(0);
  const stateRef = useRef<RealtimeState>("idle");
  const suppressAssistantOutputRef = useRef(false);
  const assistantTurnPendingRef = useRef(false);
  const pendingAudioStopTokenRef = useRef(0);

  // Calibration refs (when speechThreshold === "auto")
  const calibratingRef = useRef(false);
  const calibrationSamplesRef = useRef<number[]>([]);
  const calibrationStartRef = useRef(0);
  const calibratedThresholdRef = useRef<number | null>(null);
  const calibrationBufferRef = useRef<Int16Array[]>([]);

  // ---------------------------------------------------------------------------
  // Notify onStateChange whenever state changes
  // ---------------------------------------------------------------------------
  useEffect(() => {
    stateRef.current = state;
    configRef.current.onStateChange?.(state);
  }, [state]);

  // ---------------------------------------------------------------------------
  // Helpers — turn buffers, reconnect timer
  // ---------------------------------------------------------------------------

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  }, []);

  const clearTurnBuffers = useCallback(() => {
    currentUserTextRef.current = "";
    currentAssistantTextRef.current = "";
  }, []);

  const discardAssistantPartial = useCallback(() => {
    currentAssistantTextRef.current = "";
    setTranscript((prev) => {
      const last = prev[prev.length - 1];
      if (last && last.role === "assistant" && !last.final) {
        return prev.slice(0, -1);
      }
      return prev;
    });
  }, []);

  const finalizeAssistantPartial = useCallback(() => {
    const finalText = currentAssistantTextRef.current.trim();
    if (!finalText) return;

    configRef.current.onTranscriptUpdate?.({
      role: "assistant",
      text: finalText,
      final: true,
    });
    setTranscript((prev) => {
      const last = prev[prev.length - 1];
      if (last && last.role === "assistant" && !last.final) {
        return [
          ...prev.slice(0, -1),
          { ...last, text: finalText, final: true },
        ];
      }
      return prev;
    });
  }, []);

  const preserveAssistantPartialOnInterrupt = useCallback(() => {
    const finalText = currentAssistantTextRef.current.trim();
    if (!finalText) {
      discardAssistantPartial();
      return false;
    }

    finalizeAssistantPartial();
    currentAssistantTextRef.current = "";
    return true;
  }, [discardAssistantPartial, finalizeAssistantPartial]);

  const armAssistantOutputSuppression = useCallback(() => {
    suppressAssistantOutputRef.current = true;
  }, []);

  const clearAssistantOutputSuppression = useCallback(() => {
    suppressAssistantOutputRef.current = false;
  }, []);

  const armAssistantTurnPending = useCallback(() => {
    assistantTurnPendingRef.current = true;
  }, []);

  const clearAssistantTurnPending = useCallback(() => {
    assistantTurnPendingRef.current = false;
  }, []);

  // ---------------------------------------------------------------------------
  // Timer management
  // ---------------------------------------------------------------------------

  const resetTimerTracking = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    startTimeRef.current = 0;
    setTimer(0);
  }, []);

  useEffect(() => {
    const isActive =
      state === "connecting" ||
      state === "ready" ||
      state === "listening" ||
      state === "ai_speaking" ||
      state === "reconnecting";

    if (!isActive) {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      return;
    }

    if (!startTimeRef.current) {
      startTimeRef.current = Date.now();
    }
    if (!timerRef.current) {
      timerRef.current = setInterval(() => {
        setTimer(Math.floor((Date.now() - startTimeRef.current) / 1000));
      }, 1000);
    }
  }, [state]);

  useEffect(() => {
    return () => {
      clearReconnectTimer();
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [clearReconnectTimer]);

  // ---------------------------------------------------------------------------
  // Playback — PCM strategy (native realtime)
  // ---------------------------------------------------------------------------

  const ensurePlaybackContext = useCallback(async (): Promise<AudioContext> => {
    if (!playbackCtxRef.current) {
      const ctx = new AudioContext({ sampleRate: 24000 });
      const gainNode = ctx.createGain();
      gainNode.gain.value = isSpeakerMutedRef.current ? 0 : 1;
      gainNode.connect(ctx.destination);
      playbackCtxRef.current = ctx;
      playbackGainRef.current = gainNode;
      nextPlayTimeRef.current = ctx.currentTime;
    }
    const ctx = playbackCtxRef.current;
    if (ctx.state === "suspended") {
      await ctx.resume().catch(() => {});
    }
    return ctx;
  }, []);

  const resetPcmPlaybackQueue = useCallback(() => {
    const activeSources = playbackSourcesRef.current.splice(0);
    for (const source of activeSources) {
      source.onended = null;
      try {
        source.stop();
      } catch {
        /* already ended */
      }
      try {
        source.disconnect();
      } catch {
        /* race */
      }
    }
    if (playbackCtxRef.current) {
      nextPlayTimeRef.current = playbackCtxRef.current.currentTime;
    }
    setAiVolume(0);
  }, []);

  const closePcmPlaybackContext = useCallback(() => {
    resetPcmPlaybackQueue();
    if (playbackCtxRef.current) {
      playbackCtxRef.current.close().catch(() => {});
      playbackCtxRef.current = null;
      playbackGainRef.current = null;
      nextPlayTimeRef.current = 0;
    }
    setAiVolume(0);
  }, [resetPcmPlaybackQueue]);

  const ensureCaptureContext = useCallback(async (): Promise<AudioContext> => {
    let ctx = audioCtxRef.current;
    if (!ctx || ctx.state === "closed") {
      ctx = new AudioContext({ sampleRate: 16000 });
      audioCtxRef.current = ctx;
    }
    if (ctx.state === "suspended") {
      await ctx.resume().catch(() => {});
    }
    return ctx;
  }, []);

  const playPcmChunkDirect = useCallback((pcmData: ArrayBuffer) => {
    let ctx = playbackCtxRef.current;
    if (!ctx) {
      ctx = new AudioContext({ sampleRate: 24000 });
      const gainNode = ctx.createGain();
      gainNode.gain.value = isSpeakerMutedRef.current ? 0 : 1;
      gainNode.connect(ctx.destination);
      playbackCtxRef.current = ctx;
      playbackGainRef.current = gainNode;
      nextPlayTimeRef.current = ctx.currentTime;
    }
    if (ctx.state === "suspended") {
      void ctx.resume().catch(() => {});
    }

    const int16 = new Int16Array(pcmData);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) {
      float32[i] = int16[i] / 32768;
    }

    const buffer = ctx.createBuffer(1, float32.length, 24000);
    buffer.getChannelData(0).set(float32);
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    playbackSourcesRef.current.push(source);
    source.onended = () => {
      playbackSourcesRef.current = playbackSourcesRef.current.filter(
        (entry) => entry !== source,
      );
      try {
        source.disconnect();
      } catch {
        /* race */
      }
    };

    let sum = 0;
    for (let i = 0; i < float32.length; i++) sum += float32[i] * float32[i];
    setAiVolume(Math.sqrt(sum / float32.length));

    source.connect(playbackGainRef.current ?? ctx.destination);
    const playTime = Math.max(ctx.currentTime, nextPlayTimeRef.current);
    source.start(playTime);
    nextPlayTimeRef.current = playTime + buffer.duration;
  }, []);

  // ---------------------------------------------------------------------------
  // Playback — Blob URL / HTMLAudioElement strategy (composed realtime)
  // ---------------------------------------------------------------------------

  const clearAiPulse = useCallback(() => {
    if (aiVolumeTimeoutRef.current) {
      clearTimeout(aiVolumeTimeoutRef.current);
      aiVolumeTimeoutRef.current = null;
    }
  }, []);

  const pulseAiVolume = useCallback(() => {
    clearAiPulse();
    setAiVolume(0.7);
    aiVolumeTimeoutRef.current = setTimeout(() => {
      setAiVolume(0);
      aiVolumeTimeoutRef.current = null;
    }, 180);
  }, [clearAiPulse]);

  const resetBlobPlaybackQueue = useCallback(() => {
    clearAiPulse();
    if (playbackTimeoutRef.current) {
      clearTimeout(playbackTimeoutRef.current);
      playbackTimeoutRef.current = null;
    }
    const player = audioPlayerRef.current;
    if (player) {
      player.pause();
      player.removeAttribute("src");
      player.load();
    }
    if (activePlaybackUrlRef.current) {
      URL.revokeObjectURL(activePlaybackUrlRef.current);
      activePlaybackUrlRef.current = null;
    }
    for (const queuedUrl of playbackQueueRef.current) {
      URL.revokeObjectURL(queuedUrl);
    }
    playbackQueueRef.current = [];
    isPlaybackActiveRef.current = false;
    setAiVolume(0);
  }, [clearAiPulse]);

  const closeBlobPlaybackContext = useCallback(() => {
    resetBlobPlaybackQueue();
    clearAiPulse();
    if (audioPlayerRef.current) {
      audioPlayerRef.current.onended = null;
      audioPlayerRef.current.onerror = null;
      audioPlayerRef.current.pause();
      audioPlayerRef.current.removeAttribute("src");
      audioPlayerRef.current.load();
      audioPlayerRef.current = null;
    }
    setAiVolume(0);
  }, [clearAiPulse, resetBlobPlaybackQueue]);

  const ensureAudioPlayer = useCallback(() => {
    if (audioPlayerRef.current) return audioPlayerRef.current;
    const player = new Audio();
    player.preload = "auto";
    player.setAttribute("playsinline", "true");
    player.muted = isSpeakerMutedRef.current;
    player.onended = () => {
      if (playbackTimeoutRef.current) {
        clearTimeout(playbackTimeoutRef.current);
        playbackTimeoutRef.current = null;
      }
      clearAiPulse();
      setAiVolume(0);
      if (activePlaybackUrlRef.current) {
        URL.revokeObjectURL(activePlaybackUrlRef.current);
        activePlaybackUrlRef.current = null;
      }
      isPlaybackActiveRef.current = false;
      pumpPlaybackQueueRef.current();
    };
    player.onerror = () => {
      if (playbackTimeoutRef.current) {
        clearTimeout(playbackTimeoutRef.current);
        playbackTimeoutRef.current = null;
      }
      clearAiPulse();
      setAiVolume(0);
      if (activePlaybackUrlRef.current) {
        URL.revokeObjectURL(activePlaybackUrlRef.current);
        activePlaybackUrlRef.current = null;
      }
      isPlaybackActiveRef.current = false;
      pumpPlaybackQueueRef.current();
    };
    audioPlayerRef.current = player;
    return player;
  }, [clearAiPulse]);

  const primeBlobPlayback = useCallback(async () => {
    if (!blobPlayback || blobPlaybackPrimedRef.current) {
      return;
    }

    const player = ensureAudioPlayer();
    const previousMuted = player.muted;
    const previousVolume = player.volume;
    try {
      player.muted = true;
      player.volume = 0;
      player.src = SILENT_AUDIO_DATA_URL;
      const playPromise = player.play();
      if (playPromise) {
        await playPromise;
      }
      blobPlaybackPrimedRef.current = true;
      autoplayBlockedNoticeShownRef.current = false;
    } catch {
      if (!autoplayBlockedNoticeShownRef.current) {
        autoplayBlockedNoticeShownRef.current = true;
        configRef.current.onError?.(
          getMessage("autoplayBlocked", AUTOPLAY_BLOCKED_MESSAGE),
        );
      }
    } finally {
      try {
        player.pause();
      } catch {
        // Ignore pause races.
      }
      player.currentTime = 0;
      player.removeAttribute("src");
      player.load();
      player.muted = previousMuted;
      player.volume = previousVolume;
    }
  }, [blobPlayback, ensureAudioPlayer, getMessage]);

  const pumpPlaybackQueue = useCallback(() => {
    if (isPlaybackActiveRef.current) return;
    const nextUrl = playbackQueueRef.current.shift();
    if (!nextUrl) return;

    const player = ensureAudioPlayer();
    isPlaybackActiveRef.current = true;
    activePlaybackUrlRef.current = nextUrl;
    player.src = nextUrl;
    pulseAiVolume();
    playbackTimeoutRef.current = setTimeout(() => {
      playbackTimeoutRef.current = null;
      URL.revokeObjectURL(nextUrl);
      if (activePlaybackUrlRef.current === nextUrl) {
        activePlaybackUrlRef.current = null;
      }
      isPlaybackActiveRef.current = false;
      pumpPlaybackQueueRef.current();
    }, 15_000);
    void player
      .play()
      .then(() => {
        autoplayBlockedNoticeShownRef.current = false;
      })
      .catch(() => {
        if (playbackTimeoutRef.current) {
          clearTimeout(playbackTimeoutRef.current);
          playbackTimeoutRef.current = null;
        }
        clearAiPulse();
        setAiVolume(0);
        if (activePlaybackUrlRef.current === nextUrl) {
          URL.revokeObjectURL(nextUrl);
          activePlaybackUrlRef.current = null;
        }
        isPlaybackActiveRef.current = false;
        if (!autoplayBlockedNoticeShownRef.current) {
          autoplayBlockedNoticeShownRef.current = true;
          configRef.current.onError?.(
            getMessage("autoplayBlocked", AUTOPLAY_BLOCKED_MESSAGE),
          );
        }
        pumpPlaybackQueueRef.current();
      });
  }, [clearAiPulse, ensureAudioPlayer, getMessage, pulseAiVolume]);

  const playBlobChunk = useCallback((audioData: ArrayBuffer) => {
    const mime = audioMimeRef.current;
    const blob = new Blob([audioData], { type: mime });
    const url = URL.createObjectURL(blob);
    playbackQueueRef.current.push(url);
    pumpPlaybackQueueRef.current();
  }, []);

  useEffect(() => {
    pumpPlaybackQueueRef.current = pumpPlaybackQueue;
  }, [pumpPlaybackQueue]);

  // ---------------------------------------------------------------------------
  // Unified playback dispatch
  // ---------------------------------------------------------------------------

  const resetPlaybackQueue = useCallback(() => {
    if (blobPlayback) {
      resetBlobPlaybackQueue();
    } else {
      resetPcmPlaybackQueue();
    }
  }, [blobPlayback, resetBlobPlaybackQueue, resetPcmPlaybackQueue]);

  const closePlaybackContext = useCallback(() => {
    if (blobPlayback) {
      closeBlobPlaybackContext();
    } else {
      closePcmPlaybackContext();
    }
  }, [blobPlayback, closeBlobPlaybackContext, closePcmPlaybackContext]);

  const playAudioChunk = useCallback(
    (data: ArrayBuffer) => {
      if (blobPlayback) {
        playBlobChunk(data);
      } else {
        playPcmChunkDirect(data);
      }
    },
    [blobPlayback, playBlobChunk, playPcmChunkDirect],
  );

  useEffect(() => {
    if (audioPlayerRef.current) {
      audioPlayerRef.current.muted = isSpeakerMuted;
    }
    if (playbackGainRef.current) {
      playbackGainRef.current.gain.value = isSpeakerMuted ? 0 : 1;
    }
  }, [isSpeakerMuted]);

  // ---------------------------------------------------------------------------
  // Audio capture
  // ---------------------------------------------------------------------------

  const startCapture = useCallback(async (ws: WebSocket) => {
    let stream: MediaStream | null = null;
    let audioCtx: AudioContext | null = null;
    let processor: ScriptProcessorNode | null = null;
    let monitorGain: GainNode | null = null;

    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("Microphone access is not supported");
      }

      stream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true },
      });
      streamRef.current = stream;

      audioCtx = await ensureCaptureContext();
      audioCtxRef.current = audioCtx;

      const source = audioCtx.createMediaStreamSource(stream);
      processor = audioCtx.createScriptProcessor(
        configRef.current.audioChunkSamples ?? 4096,
        1,
        1,
      );
      processorRef.current = processor;
      monitorGain = audioCtx.createGain();
      monitorGain.gain.value = 0;
      monitorGainRef.current = monitorGain;

      // Reset VAD state
      speechActiveRef.current = false;
      hasSegmentAudioRef.current = false;
      lastSpeechAtRef.current = 0;
      interruptStartRef.current = 0;

      // Reset calibration state
      const needsCalibration =
        configRef.current.vadConfig.speechThreshold === "auto";
      calibratingRef.current = needsCalibration;
      calibrationSamplesRef.current = [];
      calibrationStartRef.current = needsCalibration ? performance.now() : 0;
      calibratedThresholdRef.current = null;
      calibrationBufferRef.current = [];

      processor.onaudioprocess = (e) => {
        if (isMutedRef.current || ws.readyState !== WebSocket.OPEN) return;

        const input = e.inputBuffer.getChannelData(0);
        let sum = 0;
        for (let i = 0; i < input.length; i++) sum += input[i] * input[i];
        const rms = Math.sqrt(sum / input.length);
        setUserVolume(rms);

        // Convert to PCM16
        const pcm = new Int16Array(input.length);
        for (let i = 0; i < input.length; i++) {
          const s = Math.max(-1, Math.min(1, input[i]));
          pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }

        const cfg = configRef.current;
        const mode = cfg.audioSendMode;
        const vad = cfg.vadConfig;
        const shouldBlockCapture =
          Boolean(cfg.blockCaptureWhileAiSpeaking) &&
          (
            stateRef.current === "ai_speaking" ||
            isPlaybackActiveRef.current
          );

        if (shouldBlockCapture) {
          speechActiveRef.current = false;
          hasSegmentAudioRef.current = false;
          interruptStartRef.current = 0;
          setUserVolume(0);
          return;
        }

        // ------ Adaptive calibration phase ------
        if (calibratingRef.current) {
          calibrationSamplesRef.current.push(rms);
          calibrationBufferRef.current.push(pcm);

          const elapsed = performance.now() - calibrationStartRef.current;
          if (elapsed >= CALIBRATION_DURATION_MS) {
            // Compute P75 of noise floor
            const sorted = [...calibrationSamplesRef.current].sort(
              (a, b) => a - b,
            );
            const p75Index = Math.floor(sorted.length * 0.75);
            const p75 = sorted[p75Index] ?? 0;
            calibratedThresholdRef.current = Math.max(
              p75 * CALIBRATION_P75_MULTIPLIER,
              CALIBRATION_MIN_THRESHOLD,
            );
            calibratingRef.current = false;

            // Flush buffered audio
            for (const bufferedPcm of calibrationBufferRef.current) {
              ws.send(bufferedPcm.buffer);
            }
            calibrationBufferRef.current = [];
            calibrationSamplesRef.current = [];
          }
          return; // Don't process audio during calibration
        }

        // ------ Determine speech threshold ------
        const threshold: number =
          vad.speechThreshold === "auto"
            ? (calibratedThresholdRef.current ?? CALIBRATION_MIN_THRESHOLD)
            : vad.speechThreshold;

        // ------ Continuous mode: send everything ------
        if (mode === "continuous") {
          ws.send(pcm.buffer);

          // Interrupt detection while a response is speaking or pending.
          if (
            cfg.enableInterrupt &&
            (
              stateRef.current === "ai_speaking" ||
              ((cfg.interruptPendingResponse ?? true) &&
                assistantTurnPendingRef.current)
            )
          ) {
            const isSpeech = rms >= threshold;
            if (isSpeech) {
              if (!interruptStartRef.current) {
                interruptStartRef.current = performance.now();
              }
              const interruptMs = vad.interruptThresholdMs ?? 400;
              if (
                performance.now() - interruptStartRef.current >=
                interruptMs
              ) {
                armAssistantOutputSuppression();
                ws.send(JSON.stringify({ type: "input.interrupt" }));
                interruptStartRef.current = 0;
              }
            } else {
              const cooldown = vad.speechCooldownMs ?? 200;
              if (
                interruptStartRef.current &&
                performance.now() - interruptStartRef.current > cooldown
              ) {
                interruptStartRef.current = 0;
              }
            }
          }
          return;
        }

        // ------ VAD-gated mode: send only speech segments ------
        const now = performance.now();
        const isSpeech = rms >= threshold;
        if (isSpeech) {
          if (pendingAudioStopTokenRef.current) {
            pendingAudioStopTokenRef.current += 1;
          }
          speechActiveRef.current = true;
          lastSpeechAtRef.current = now;
        }

        const silenceCommitMs = vad.silenceCommitMs ?? 420;
        const shouldSendChunk =
          isSpeech ||
          (speechActiveRef.current &&
            now - lastSpeechAtRef.current < silenceCommitMs);

        if (!shouldSendChunk) {
          if (speechActiveRef.current && hasSegmentAudioRef.current) {
            speechActiveRef.current = false;
            hasSegmentAudioRef.current = false;
            setUserVolume(0);
            const stopToken = pendingAudioStopTokenRef.current + 1;
            pendingAudioStopTokenRef.current = stopToken;
            void Promise.resolve(cfg.beforeAudioStop?.())
              .catch(() => undefined)
              .finally(() => {
                if (pendingAudioStopTokenRef.current !== stopToken) {
                  return;
                }
                pendingAudioStopTokenRef.current = 0;
                if (ws.readyState === WebSocket.OPEN) {
                  ws.send(JSON.stringify({ type: "audio.stop" }));
                }
              });
          }
          return;
        }

        // Interrupt detection while a response is speaking or pending.
        if (
          cfg.enableInterrupt &&
          (
            stateRef.current === "ai_speaking" ||
            ((cfg.interruptPendingResponse ?? true) &&
              assistantTurnPendingRef.current)
          ) &&
          isSpeech
        ) {
          if (!interruptStartRef.current) {
            interruptStartRef.current = now;
          }
          const interruptMs = vad.interruptThresholdMs ?? 400;
          if (now - interruptStartRef.current >= interruptMs) {
            armAssistantOutputSuppression();
            ws.send(JSON.stringify({ type: "input.interrupt" }));
            interruptStartRef.current = 0;
          }
        } else if (!isSpeech) {
          interruptStartRef.current = 0;
        }

        hasSegmentAudioRef.current = true;
        ws.send(pcm.buffer);
      };

      source.connect(processor);
      processor.connect(monitorGain);
      monitorGain.connect(audioCtx.destination);
    } catch (error) {
      processor?.disconnect();
      monitorGain?.disconnect();
      if (audioCtx) {
        await audioCtx.close().catch(() => {});
      }
      if (monitorGainRef.current === monitorGain) monitorGainRef.current = null;
      if (audioCtxRef.current === audioCtx) audioCtxRef.current = null;
      stream?.getTracks().forEach((track) => track.stop());
      if (streamRef.current === stream) streamRef.current = null;
      setUserVolume(0);
      throw error;
    }
  }, [ensureCaptureContext]);

  const stopCapture = useCallback(() => {
    // In vad-gated mode, flush pending segment
    if (
      configRef.current.audioSendMode === "vad-gated" &&
      hasSegmentAudioRef.current &&
      wsRef.current &&
      wsRef.current.readyState === WebSocket.OPEN
    ) {
      try {
        wsRef.current.send(JSON.stringify({ type: "audio.stop" }));
      } catch {
        // ignore close races
      }
    }
    processorRef.current?.disconnect();
    processorRef.current = null;
    monitorGainRef.current?.disconnect();
    monitorGainRef.current = null;
    audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    speechActiveRef.current = false;
    hasSegmentAudioRef.current = false;
    pendingAudioStopTokenRef.current = 0;
    interruptStartRef.current = 0;
    calibratingRef.current = false;
    calibrationBufferRef.current = [];
    calibrationSamplesRef.current = [];
    setUserVolume(0);
  }, []);

  // ---------------------------------------------------------------------------
  // teardown / finalize helpers
  // ---------------------------------------------------------------------------

  const teardownMedia = useCallback(
    (options?: { closePlayback?: boolean }) => {
      wsRef.current = null;
      stopCapture();
      if (options?.closePlayback === false) {
        resetPlaybackQueue();
        return;
      }
      closePlaybackContext();
    },
    [closePlaybackContext, resetPlaybackQueue, stopCapture],
  );

  const finalizeConnection = useCallback(
    (
      nextState: RealtimeState,
      options?: { clearTranscript?: boolean; message?: string },
    ) => {
      clearReconnectTimer();
      clearAssistantOutputSuppression();
      clearAssistantTurnPending();
      teardownMedia();
      clearTurnBuffers();
      resetTimerTracking();
      if (options?.clearTranscript) {
        setTranscript([]);
      }
      setState(nextState);
      if (options?.message) {
        configRef.current.onError?.(options.message);
      }
    },
    [
      clearAssistantOutputSuppression,
      clearAssistantTurnPending,
      clearReconnectTimer,
      clearTurnBuffers,
      resetTimerTracking,
      teardownMedia,
    ],
  );

  const scheduleReconnect = useCallback(() => {
    if (reconnectAttemptsRef.current >= MAX_RECONNECT_ATTEMPTS) {
      finalizeConnection("error", {
        message: getMessage(
          "websocketConnectionFailed",
          WEBSOCKET_CONNECTION_FAILED_MESSAGE,
        ),
      });
      return;
    }

    teardownMedia({ closePlayback: false });
    const delayMs = Math.min(500 * 2 ** reconnectAttemptsRef.current, 2000);
    reconnectAttemptsRef.current += 1;
    setState("reconnecting");
    reconnectTimeoutRef.current = setTimeout(() => {
      reconnectTimeoutRef.current = null;
      void openConnectionRef.current("reconnect");
    }, delayMs);
  }, [finalizeConnection, getMessage, teardownMedia]);

  // ---------------------------------------------------------------------------
  // WS message handler
  // ---------------------------------------------------------------------------

  const handleWsMessage = useCallback(
    async (event: MessageEvent, ws: WebSocket) => {
      if (event.data instanceof ArrayBuffer) {
        if (suppressAssistantOutputRef.current) {
          return;
        }
        clearAssistantTurnPending();
        playAudioChunk(event.data);
        setState("ai_speaking");
        return;
      }
      if (event.data instanceof Blob) {
        if (suppressAssistantOutputRef.current) {
          return;
        }
        clearAssistantTurnPending();
        playAudioChunk(await event.data.arrayBuffer());
        setState("ai_speaking");
        return;
      }

      const msg = JSON.parse(event.data);
      const cfg = configRef.current;

      switch (msg.type) {
        case "session.ready":
          clearAssistantOutputSuppression();
          clearAssistantTurnPending();
          reconnectAttemptsRef.current = 0;
          setState("ready");
          cfg.onSessionReady?.(ws);
          try {
            await startCapture(ws);
            setState("listening");
          } catch {
            terminalErrorMessageRef.current = getMessage(
              "microphonePermissionRequired",
              MICROPHONE_PERMISSION_REQUIRED_MESSAGE,
            );
            ws.close();
          }
          break;

        case "transcript.partial":
          cfg.onTranscriptUpdate?.({
            role: "user",
            text: msg.text || "",
            final: false,
          });
          setTranscript((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.role === "user" && !last.final) {
              return [
                ...prev.slice(0, -1),
                { role: "user", text: msg.text, final: false },
              ];
            }
            return [...prev, { role: "user", text: msg.text, final: false }];
          });
          break;

        case "transcript.final":
          // Flush any audio still queued from the previous AI response so the
          // new response plays immediately instead of waiting for old audio.
          resetPlaybackQueue();
          clearAssistantOutputSuppression();
          armAssistantTurnPending();
          currentUserTextRef.current = msg.text || "";
          cfg.onTranscriptUpdate?.({
            role: "user",
            text: msg.text || "",
            final: true,
          });
          setTranscript((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.role === "user" && !last.final) {
              return [
                ...prev.slice(0, -1),
                { role: "user", text: msg.text, final: true },
              ];
            }
            return [...prev, { role: "user", text: msg.text, final: true }];
          });
          break;

        case "response.text":
          if (suppressAssistantOutputRef.current) {
            break;
          }
          clearAssistantTurnPending();
          currentAssistantTextRef.current = msg.replace
            ? msg.text || ""
            : currentAssistantTextRef.current + (msg.text || "");
          cfg.onTranscriptUpdate?.({
            role: "assistant",
            text: currentAssistantTextRef.current,
            final: false,
          });
          setTranscript((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.role === "assistant" && !last.final) {
              return [
                ...prev.slice(0, -1),
                {
                  role: "assistant",
                  text: msg.replace
                    ? msg.text || ""
                    : last.text + (msg.text || ""),
                  final: false,
                },
              ];
            }
            return [
              ...prev,
              { role: "assistant", text: msg.text, final: false },
            ];
          });
          break;

        case "response.done":
          if (suppressAssistantOutputRef.current) {
            break;
          }
          clearAssistantTurnPending();
          cfg.onTranscriptUpdate?.({
            role: "assistant",
            text: currentAssistantTextRef.current,
            final: true,
          });
          setTranscript((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.role === "assistant") {
              return [...prev.slice(0, -1), { ...last, final: true }];
            }
            return prev;
          });
          if (currentUserTextRef.current || currentAssistantTextRef.current) {
            cfg.onTurnComplete?.({
              userText: currentUserTextRef.current.trim(),
              assistantText: currentAssistantTextRef.current.trim(),
            });
          }
          clearTurnBuffers();
          reconnectAttemptsRef.current = 0;
          setState("listening");
          break;

        case "interrupt.ack":
          armAssistantOutputSuppression();
          clearAssistantTurnPending();
          resetPlaybackQueue();
          if (!preserveAssistantPartialOnInterrupt()) {
            cfg.onTranscriptUpdate?.({
              role: "assistant",
              text: "",
              final: false,
              action: "discard",
            });
          }
          setState("listening");
          break;

        case "audio.meta":
          if (suppressAssistantOutputRef.current) {
            break;
          }
          audioMimeRef.current = msg.mime || "audio/mpeg";
          break;

        case "session.idle":
          break;

        case "session.end":
          clearAssistantTurnPending();
          sessionEndReasonRef.current =
            typeof msg.reason === "string" ? msg.reason : "";
          ws.close();
          break;

        case "error":
          clearAssistantTurnPending();
          terminalErrorMessageRef.current =
            msg.code === "model_api_unconfigured"
              ? "model_api_unconfigured"
              : msg.message || "Unknown error";
          ws.close();
          break;

        case "turn.error":
          clearAssistantTurnPending();
          finalizeAssistantPartial();
          clearTurnBuffers();
          setState("listening");
          cfg.onError?.(
            msg.message || getMessage("turnError", "本轮处理失败，请重试"),
          );
          cfg.onCustomMessage?.(msg as Record<string, unknown>, ws);
          break;

        case "turn.notice":
          cfg.onError?.(
            msg.message || getMessage("turnNotice", "语音输出暂时不可用"),
          );
          cfg.onCustomMessage?.(msg as Record<string, unknown>, ws);
          break;

        default:
          // Pass unrecognized messages to the wrapper
          cfg.onCustomMessage?.(msg as Record<string, unknown>, ws);
          break;
      }
    },
    [
      armAssistantOutputSuppression,
      armAssistantTurnPending,
      clearAssistantOutputSuppression,
      clearAssistantTurnPending,
      clearTurnBuffers,
      finalizeAssistantPartial,
      getMessage,
      playAudioChunk,
      preserveAssistantPartialOnInterrupt,
      resetPlaybackQueue,
      startCapture,
    ],
  );

  // ---------------------------------------------------------------------------
  // openConnection
  // ---------------------------------------------------------------------------

  const buildWebSocketUrl = useCallback(async (wsPath: string) => {
    const apiBaseUrl = new URL(getApiBaseUrl());
    const protocol = apiBaseUrl.protocol === "https:" ? "wss:" : "ws:";
    const { ticket } = await apiGet<RealtimeWsTicketResponse>(
      "/api/v1/realtime/ws-ticket",
    );
    const wsUrl = new URL(`${protocol}//${apiBaseUrl.host}${wsPath}`);
    if (ticket) {
      wsUrl.searchParams.set("ticket", ticket);
    }
    return wsUrl.toString();
  }, []);

  const openConnection = useCallback(
    async (mode: "connect" | "reconnect") => {
      const existingSocket = wsRef.current;
      if (
        existingSocket &&
        (existingSocket.readyState === WebSocket.OPEN ||
          existingSocket.readyState === WebSocket.CONNECTING)
      ) {
        return;
      }

      clearReconnectTimer();
      clearAssistantOutputSuppression();
      clearAssistantTurnPending();
      manualDisconnectRef.current = false;
      terminalErrorMessageRef.current = null;
      sessionEndReasonRef.current = null;

      if (mode === "connect") {
        reconnectAttemptsRef.current = 0;
        clearTurnBuffers();
        setTranscript([]);
        resetTimerTracking();
        autoplayBlockedNoticeShownRef.current = false;
      }

      setState(mode === "reconnect" ? "reconnecting" : "connecting");
      if (!startTimeRef.current) {
        startTimeRef.current = Date.now();
      }

      const cfg = configRef.current;
      let wsUrl = "";
      try {
        wsUrl = await buildWebSocketUrl(cfg.wsPath);
      } catch (error) {
        finalizeConnection("error", {
          message:
            isApiRequestError(error) && error.message
              ? error.message
              : getMessage(
                  "websocketConnectionFailed",
                  WEBSOCKET_CONNECTION_FAILED_MESSAGE,
                ),
        });
        return;
      }

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      ws.binaryType = "arraybuffer";

      ws.onopen = () => {
        ws.send(
          JSON.stringify({
            type: "session.start",
            conversation_id: cfg.conversationId,
            project_id: cfg.projectId,
            ...(cfg.sessionStartPayload || {}),
          }),
        );
      };

      ws.onmessage = (event) => {
        void handleWsMessage(event, ws);
      };

      ws.onclose = (event) => {
        const errorMessage = terminalErrorMessageRef.current;
        const sessionEndReason = sessionEndReasonRef.current;
        terminalErrorMessageRef.current = null;
        sessionEndReasonRef.current = null;

        if (manualDisconnectRef.current) {
          manualDisconnectRef.current = false;
          finalizeConnection("idle", { clearTranscript: true });
          return;
        }

        if (errorMessage) {
          finalizeConnection("error", { message: errorMessage });
          return;
        }

        if (sessionEndReason) {
          finalizeConnection(
            sessionEndReason === "auth_revoked" ? "error" : "idle",
            sessionEndReason === "auth_revoked"
              ? { message: "Authentication expired" }
              : undefined,
          );
          return;
        }

        if (event.code === 1000) {
          finalizeConnection("idle");
          return;
        }

        scheduleReconnect();
      };

      ws.onerror = () => undefined;
    },
    [
      buildWebSocketUrl,
      clearAssistantOutputSuppression,
      clearAssistantTurnPending,
      clearReconnectTimer,
      clearTurnBuffers,
      finalizeConnection,
      handleWsMessage,
      getMessage,
      resetTimerTracking,
      scheduleReconnect,
    ],
  );

  // Keep openConnectionRef in sync
  useEffect(() => {
    openConnectionRef.current = openConnection;
  }, [openConnection]);

  // ---------------------------------------------------------------------------
  // Conversation context change → tear down and notify
  // ---------------------------------------------------------------------------

  useEffect(() => {
    const nextContextKey = `${projectId}:${conversationId}`;
    if (sessionContextRef.current === nextContextKey) return;
    sessionContextRef.current = nextContextKey;

    const hasLiveSession =
      wsRef.current !== null ||
      state === "connecting" ||
      state === "ready" ||
      state === "listening" ||
      state === "ai_speaking" ||
      state === "reconnecting";

    if (!hasLiveSession) return;

    clearReconnectTimer();
    clearAssistantOutputSuppression();
    clearAssistantTurnPending();
    manualDisconnectRef.current = true;
    terminalErrorMessageRef.current = null;
    sessionEndReasonRef.current = null;

    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type: "session.end" }));
      } catch {
        // ignore close races
      }
    }
    ws?.close();
    finalizeConnection("idle", {
      clearTranscript: true,
      message: "Conversation changed. Please restart voice.",
    });
  }, [
    clearAssistantOutputSuppression,
    clearAssistantTurnPending,
    clearReconnectTimer,
    conversationId,
    finalizeConnection,
    projectId,
    state,
  ]);

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  const disconnect = useCallback(() => {
    clearReconnectTimer();
    clearAssistantOutputSuppression();
    clearAssistantTurnPending();
    manualDisconnectRef.current = true;
    terminalErrorMessageRef.current = null;
    sessionEndReasonRef.current = null;

    const ws = wsRef.current;
    if (!ws || ws.readyState === WebSocket.CLOSED) {
      finalizeConnection("idle", { clearTranscript: true });
      return;
    }

    if (ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type: "session.end" }));
      } catch {
        // Ignore close races.
      }
    }
    ws.close();
  }, [
    clearAssistantOutputSuppression,
    clearAssistantTurnPending,
    clearReconnectTimer,
    finalizeConnection,
  ]);

  const connect = useCallback(async () => {
    if (state !== "idle" && state !== "error") return;
    // Keep connection setup in the same user gesture. Deferring it to a timer
    // can prevent some browsers / external microphones from activating capture.
    await ensureCaptureContext();
    if (!blobPlayback) {
      await ensurePlaybackContext();
    } else {
      void primeBlobPlayback();
    }
    await openConnection("connect");
  }, [
    blobPlayback,
    ensureCaptureContext,
    ensurePlaybackContext,
    openConnection,
    primeBlobPlayback,
    state,
  ]);

  const toggleMute = useCallback(() => {
    setIsMuted((prev) => {
      isMutedRef.current = !prev;
      return !prev;
    });
  }, []);

  const toggleSpeakerMute = useCallback(() => {
    setIsSpeakerMuted((prev) => {
      const next = !prev;
      isSpeakerMutedRef.current = next;
      return next;
    });
  }, []);

  const sendJson = useCallback((data: Record<string, unknown>) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      if (data.type === "input.interrupt") {
        armAssistantOutputSuppression();
      }
      ws.send(JSON.stringify(data));
    }
  }, [armAssistantOutputSuppression]);

  const sendBinary = useCallback((data: ArrayBuffer) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(data);
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  return {
    state,
    transcript,
    timer,
    connect,
    disconnect,
    toggleMute,
    isMuted,
    toggleSpeakerMute,
    isSpeakerMuted,
    userVolume,
    aiVolume,
    sendJson,
    sendBinary,
  };
}
