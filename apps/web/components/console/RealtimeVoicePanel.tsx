"use client";

import { useCallback, useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import {
  useRealtimeVoice,
  type PersistedRealtimeTurnPayload,
} from "@/hooks/useRealtimeVoice";
import { useSyntheticRealtimeVoice } from "@/hooks/useSyntheticRealtimeVoice";
import { useRealtimeCamera } from "@/hooks/useRealtimeCamera";
import { useSyntheticRealtimeCamera } from "@/hooks/useSyntheticRealtimeCamera";
import type { ChatMode } from "./chat-types";

interface RealtimeVoicePanelProps {
  chatMode: ChatMode; // "omni_realtime" | "synthetic_realtime"
  conversationId: string;
  projectId: string;
  allowVideoInput?: boolean;
  onTurnComplete: (payload: {
    userText: string;
    assistantText: string;
  }) => void;
  onTurnPersisted: (payload: PersistedRealtimeTurnPayload) => void;
  onTranscriptUpdate: (payload: {
    role: "user" | "assistant";
    text: string;
    final: boolean;
    action?: "upsert" | "discard";
  }) => void;
  onError: (msg: string) => void;
  onStateChange: (state: string) => void;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function WaveformBars({
  levels,
  barCount = 5,
}: {
  levels: number[];
  barCount?: number;
}) {
  return (
    <div className={`rt-waveform${barCount > 5 ? " is-large" : ""}`}>
      {Array.from({ length: barCount }, (_, i) => (
        <div
          key={i}
          className="rt-waveform-bar"
          style={{ height: `${(levels[i % levels.length] || 0.15) * 100}%` }}
        />
      ))}
    </div>
  );
}

/** Convert volume (0-1) to an array of bar levels for WaveformBars */
function volumeToLevels(volume: number, count: number): number[] {
  return Array.from({ length: count }, (_, i) => {
    const base = 0.15;
    const h = base + volume * (1 + Math.sin(i * 1.2)) * 0.42;
    return Math.min(h, 1);
  });
}

export default function RealtimeVoicePanel({
  chatMode,
  conversationId,
  projectId,
  allowVideoInput = false,
  onTurnComplete,
  onTurnPersisted,
  onTranscriptUpdate,
  onError,
  onStateChange,
}: RealtimeVoicePanelProps) {
  const t = useTranslations("console-chat");
  const sessionKey = `${chatMode}:${projectId}:${conversationId}`;
  const cameraPreviewRef = useRef<HTMLVideoElement>(null);

  const isSynthetic = chatMode === "synthetic_realtime";

  const handleRealtimeError = useCallback(
    (msg: string) => {
      const friendlyMessage =
        msg === "model_api_unconfigured" ? t("errors.modelUnconfigured") : msg;
      console.error("[RealtimeVoicePanel]", friendlyMessage);
      onError(friendlyMessage);
    },
    [onError, t],
  );

  const localizedRealtimeMessages = {
    autoplayBlocked: t("errors.autoplayBlocked"),
    microphonePermissionRequired: t("errors.microphoneRequired"),
    websocketConnectionFailed: t("errors.connectionFailed"),
    turnError: t("errors.turnProcessingFailed"),
    turnNotice: t("errors.audioTemporarilyUnavailable"),
  };

  // IMPORTANT: Both hooks must be called unconditionally to satisfy React's
  // rules of hooks. Both start idle; only the active one's connect() is called.
  const omni = useRealtimeVoice({
    conversationId,
    projectId,
    onTurnComplete,
    onTurnPersisted,
    onTranscriptUpdate,
    onError: handleRealtimeError,
    messages: localizedRealtimeMessages,
  });

  const synthetic = useSyntheticRealtimeVoice({
    conversationId,
    projectId,
    onTurnComplete,
    onTurnPersisted,
    onTranscriptUpdate,
    onError: handleRealtimeError,
    messages: localizedRealtimeMessages,
  });

  // Select active hook result based on chatMode
  const active = isSynthetic ? synthetic : omni;
  const {
    state,
    timer,
    connect,
    disconnect,
    toggleMute,
    isMuted,
    toggleSpeakerMute,
    isSpeakerMuted,
    userVolume,
    aiVolume,
  } = active;
  const omniState = omni.state;
  const omniTranscriptLength = omni.transcript.length;
  const omniDisconnect = omni.disconnect;
  const syntheticState = synthetic.state;
  const syntheticTranscriptLength = synthetic.transcript.length;
  const syntheticDisconnect = synthetic.disconnect;

  // Synthetic-only fields
  const pendingMedia = isSynthetic ? synthetic.pendingMedia : null;
  const syntheticCamera = useSyntheticRealtimeCamera({
    enabled: isSynthetic && allowVideoInput,
    sessionState: synthetic.state,
    sessionKey,
    turnBoundaryCount: synthetic.turnBoundaryCount,
    sendJson: synthetic.sendJson,
    onError: handleRealtimeError,
    messages: {
      cameraPermissionRequired: t("errors.cameraRequired"),
      cameraUnavailable: t("errors.cameraUnavailable"),
    },
  });
  const camera = useRealtimeCamera({
    enabled: !isSynthetic,
    sessionState: omni.state,
    sessionKey,
    sendJson: omni.sendJson,
    onError: handleRealtimeError,
    messages: {
      cameraPermissionRequired: t("errors.cameraRequired"),
      cameraUnavailable: t("errors.cameraUnavailable"),
    },
  });
  const activeCamera = isSynthetic ? syntheticCamera : camera;

  useEffect(() => {
    const preview = cameraPreviewRef.current;
    if (!preview) {
      return;
    }

    preview.srcObject = activeCamera.previewStream;
    if (activeCamera.previewStream) {
      void preview.play().catch(() => undefined);
    } else {
      preview.removeAttribute("src");
      preview.load();
    }

    return () => {
      if (preview.srcObject === activeCamera.previewStream) {
        preview.srcObject = null;
      }
    };
  }, [activeCamera.previewStream]);

  useEffect(() => {
    onStateChange(state);
  }, [onStateChange, state]);

  const sessionIdentityRef = useRef(sessionKey);
  useEffect(() => {
    if (sessionIdentityRef.current === sessionKey) {
      return;
    }
    const hadActiveSession =
      omniState !== "idle" ||
      syntheticState !== "idle" ||
      omniTranscriptLength > 0 ||
      syntheticTranscriptLength > 0;
    sessionIdentityRef.current = sessionKey;
    omniDisconnect();
    syntheticDisconnect();
    if (hadActiveSession) {
      onError(t("realtimeRestartAfterContextChange"));
    }
  }, [
    conversationId,
    omniDisconnect,
    omniState,
    omniTranscriptLength,
    onError,
    projectId,
    sessionKey,
    syntheticDisconnect,
    syntheticState,
    syntheticTranscriptLength,
    t,
  ]);

  const isListening = state === "listening" || state === "ready";
  const isSpeaking = state === "ai_speaking";

  // Derive status class for the dot indicator
  const statusClass = isMuted
    ? "muted"
    : isSpeaking
      ? "speaking"
      : isListening
        ? "listening"
        : state === "connecting" || state === "reconnecting"
          ? "connecting"
          : state === "error"
            ? "error"
            : "idle";

  const waveformLevels = volumeToLevels(isListening ? userVolume : aiVolume, 8);

  const entryLabel = isSynthetic ? t("syntheticEntry") : t("realtimeEntry");
  const statusText =
    state === "error"
      ? t("realtimeConnectionFailed")
      : state === "connecting" || state === "reconnecting"
      ? t("realtimePreparing")
      : isSpeaking
        ? t("realtimeSpeaking")
        : isListening
          ? t("realtimeListening")
          : entryLabel;
  const assistantTitle = isSynthetic
    ? t("syntheticAssistant")
    : t("realtimeAssistant");
  const startButtonLabel =
    state === "error"
      ? t("realtimeRetry")
      : state === "connecting" || state === "reconnecting"
        ? t("realtimePreparing")
        : t("realtimeStageStart");
  const stageSupportingText =
    state === "error"
      ? t("realtimeConnectionFailed")
      : state === "connecting" || state === "reconnecting"
        ? t("realtimePreparing")
        : isSynthetic
          ? allowVideoInput
            ? syntheticCamera.isCameraActive
              ? t("syntheticCameraLive")
              : syntheticCamera.isCameraSupported
                ? t("syntheticCameraOff")
                : t("syntheticCameraUnsupported")
            : pendingMedia
              ? pendingMedia.filename
              : t("syntheticUploadImageOnly")
          : camera.isCameraActive
            ? t("realtimeCameraLive")
            : camera.isCameraSupported
              ? t("realtimeCameraOff")
              : t("realtimeCameraUnsupported");
  const visualLabel = isSynthetic ? t("syntheticVideo") : t("realtimeVisualTitle");
  const canStartSession =
    state === "idle" ||
    state === "error" ||
    state === "connecting" ||
    state === "reconnecting";

  const handleHangup = useCallback(() => {
    disconnect();
  }, [disconnect]);

  return (
    <div className={`rt-inline${isSynthetic ? " is-synthetic" : " is-omni"}`}>
      <div className="rt-inline-frame">
        <div className="rt-inline-body">
          <div className="rt-inline-preview-block">
            <div className="rt-inline-panel-head">
              <span className="rt-stage-section-label">{visualLabel}</span>
              {(!isSynthetic || allowVideoInput) && (
                <span
                  className={`rt-camera-badge${activeCamera.isCameraActive ? " is-live" : ""}`}
                >
                  {activeCamera.isCameraActive
                    ? t("realtimeCameraLive")
                    : t("realtimeCameraIdle")}
                </span>
              )}
            </div>
            <div className="rt-camera-panel rt-camera-panel--inline">
              <div className="rt-camera-preview-shell rt-camera-preview-shell--inline">
                {activeCamera.isCameraEnabled && activeCamera.previewStream ? (
                  <video
                    ref={cameraPreviewRef}
                    className="rt-camera-video"
                    autoPlay
                    muted
                    playsInline
                  />
                ) : (
                  <div className="rt-camera-placeholder">
                    {isSynthetic
                      ? allowVideoInput
                        ? syntheticCamera.isCameraSupported
                          ? t("syntheticCameraOff")
                          : t("syntheticCameraUnsupported")
                        : pendingMedia
                          ? pendingMedia.filename
                          : t("syntheticMediaDescription")
                      : camera.isCameraSupported
                        ? t("realtimeCameraOff")
                        : t("realtimeCameraUnsupported")}
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="rt-inline-main">
            <div className="rt-inline-header">
              <div className="rt-inline-heading">
                <span className={`rt-status-dot is-${statusClass}`} />
                <div className="rt-inline-heading-copy">
                  <span className="rt-card-title">{assistantTitle}</span>
                  <span className="rt-stage-mode">{entryLabel}</span>
                </div>
              </div>
              <div className="rt-stage-meta">
                <span className="rt-stage-pill">{statusText}</span>
                <span className="rt-card-timer">{formatTime(timer)}</span>
              </div>
            </div>

            <div className="rt-inline-copy">
              <strong className="rt-stage-status-text">{statusText}</strong>
              <p className="rt-stage-status-copy">{stageSupportingText}</p>
            </div>

            <div className="rt-inline-action-row">
              {canStartSession ? (
                <button
                  type="button"
                  className="rt-capsule rt-entry rt-entry--dock"
                  onClick={connect}
                  disabled={state === "connecting" || state === "reconnecting"}
                  aria-label={startButtonLabel}
                >
                  <span className="rt-capsule-label rt-entry-label">
                    {startButtonLabel}
                  </span>
                </button>
              ) : (
                <div className="rt-stage-status-card rt-stage-status-card--inline">
                  <WaveformBars levels={waveformLevels} barCount={8} />
                </div>
              )}
            </div>

            {!isSynthetic ? (
              <div className="rt-camera-toolbar rt-camera-toolbar--inline">
                <button
                  type="button"
                  className={`chat-audio-btn${camera.isCameraEnabled ? " is-active" : ""}`}
                  onClick={camera.toggleCamera}
                  disabled={!camera.isCameraSupported}
                >
                  {camera.isCameraEnabled
                    ? t("realtimeCameraDisable")
                    : t("realtimeCameraEnable")}
                </button>
                {camera.videoDevices.length > 1 && (
                  <button
                    type="button"
                    className="chat-audio-btn"
                    onClick={camera.cycleDevice}
                  >
                    {t("realtimeCameraSwitch")}
                  </button>
                )}
                {camera.videoDevices.length > 0 ? (
                  <select
                    className="rt-camera-select"
                    aria-label={t("realtimeCameraSelect")}
                    value={camera.selectedDeviceId || ""}
                    onChange={(event) => camera.selectDevice(event.target.value)}
                  >
                    {camera.videoDevices.map((device) => (
                      <option key={device.deviceId} value={device.deviceId}>
                        {device.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span className="rt-camera-empty">
                    {t("realtimeCameraNoDevices")}
                  </span>
                )}
              </div>
            ) : allowVideoInput ? (
              <div className="rt-camera-toolbar rt-camera-toolbar--inline">
                <button
                  type="button"
                  className={`chat-audio-btn${syntheticCamera.isCameraEnabled ? " is-active" : ""}`}
                  onClick={syntheticCamera.toggleCamera}
                  disabled={!syntheticCamera.isCameraSupported}
                >
                  {syntheticCamera.isCameraEnabled
                    ? t("realtimeCameraDisable")
                    : t("realtimeCameraEnable")}
                </button>
                {syntheticCamera.videoDevices.length > 1 && (
                  <button
                    type="button"
                    className="chat-audio-btn"
                    onClick={syntheticCamera.cycleDevice}
                  >
                    {t("realtimeCameraSwitch")}
                  </button>
                )}
                {syntheticCamera.videoDevices.length > 0 ? (
                  <select
                    className="rt-camera-select"
                    aria-label={t("realtimeCameraSelect")}
                    value={syntheticCamera.selectedDeviceId || ""}
                    onChange={(event) =>
                      syntheticCamera.selectDevice(event.target.value)
                    }
                  >
                    {syntheticCamera.videoDevices.map((device) => (
                      <option key={device.deviceId} value={device.deviceId}>
                        {device.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span className="rt-camera-empty">
                    {t("realtimeCameraNoDevices")}
                  </span>
                )}
              </div>
            ) : (
              <div className="rt-media-toolbar rt-media-toolbar--inline">
                {pendingMedia && (
                  <button
                    type="button"
                    className="chat-audio-btn"
                    onClick={synthetic.clearPendingMedia}
                  >
                    {t("syntheticClearMedia")}
                  </button>
                )}
                <span className="rt-camera-empty">
                  {t("syntheticCameraUnsupported")}
                </span>
              </div>
            )}

            <div className="rt-card-controls rt-card-controls--inline">
              <button
                className={`rt-card-control-btn${isMuted ? " is-muted" : ""}`}
                onClick={toggleMute}
                title={isMuted ? t("realtimeUnmute") : t("realtimeMute")}
              >
                <svg
                  viewBox="0 0 24 24"
                  width={20}
                  height={20}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                  <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                  <line x1="12" y1="19" x2="12" y2="23" />
                  {isMuted && (
                    <line
                      x1="1"
                      y1="1"
                      x2="23"
                      y2="23"
                      stroke="#ef4444"
                      strokeWidth={2.5}
                    />
                  )}
                </svg>
              </button>

              <button className="rt-card-hangup" onClick={handleHangup}>
                <svg viewBox="0 0 24 24" width={20} height={20} fill="currentColor">
                  <line
                    x1="18"
                    y1="6"
                    x2="6"
                    y2="18"
                    stroke="currentColor"
                    strokeWidth={2.5}
                  />
                  <line
                    x1="6"
                    y1="6"
                    x2="18"
                    y2="18"
                    stroke="currentColor"
                    strokeWidth={2.5}
                  />
                </svg>
              </button>

              <button
                type="button"
                className={`rt-card-control-btn${isSpeakerMuted ? " is-muted" : ""}`}
                title={t("realtimeSpeaker")}
                onClick={toggleSpeakerMute}
              >
                <svg
                  viewBox="0 0 24 24"
                  width={20}
                  height={20}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
                  <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
                  <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
                  {isSpeakerMuted && (
                    <line
                      x1="2"
                      y1="2"
                      x2="22"
                      y2="22"
                      stroke="#ef4444"
                      strokeWidth={2.5}
                    />
                  )}
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
