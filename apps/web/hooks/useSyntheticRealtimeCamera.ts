"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { RealtimeState } from "./useRealtimeVoiceBase";
import type { RealtimeCameraDevice } from "./useRealtimeCamera";

const CAMERA_STORAGE_KEY = "qihang.synthetic.camera.deviceId";
const FRAME_INTERVAL_MS = 1000;
const MAX_FRAME_BYTES = 500 * 1024;
const FRAME_MAX_LONG_EDGES = [1280, 960, 720];
const JPEG_QUALITIES = [0.72, 0.6, 0.48, 0.4];
const SYNTHETIC_VIDEO_FPS = 1;

interface UseSyntheticRealtimeCameraOptions {
  enabled: boolean;
  sessionState: RealtimeState;
  sessionKey: string;
  turnBoundaryCount: number;
  sendJson: (data: Record<string, unknown>) => void;
  onError?: (message: string) => void;
  messages?: {
    cameraPermissionRequired?: string;
    cameraUnavailable?: string;
  };
}

interface UseSyntheticRealtimeCameraReturn {
  isCameraSupported: boolean;
  isCameraEnabled: boolean;
  isCameraActive: boolean;
  previewStream: MediaStream | null;
  videoDevices: RealtimeCameraDevice[];
  selectedDeviceId: string | null;
  toggleCamera: () => void;
  selectDevice: (deviceId: string) => void;
  cycleDevice: () => void;
}

function stopTracks(stream: MediaStream | null): void {
  stream?.getTracks().forEach((track) => track.stop());
}

function estimateDataUrlBytes(dataUrl: string): number {
  const commaIndex = dataUrl.indexOf(",");
  if (commaIndex < 0) {
    return Number.POSITIVE_INFINITY;
  }
  const base64 = dataUrl.slice(commaIndex + 1);
  const paddingLength = (base64.match(/=+$/)?.[0].length ?? 0);
  return Math.max(0, Math.floor((base64.length * 3) / 4) - paddingLength);
}

function normalizeDeviceLabel(device: MediaDeviceInfo, index: number): string {
  const label = String(device.label || "").trim();
  return label || `Camera ${index + 1}`;
}

function buildVideoConstraints(deviceId: string | null): MediaTrackConstraints {
  if (deviceId) {
    return {
      deviceId: { exact: deviceId },
      width: { ideal: 1280 },
      height: { ideal: 720 },
      frameRate: { ideal: 12, max: 15 },
    };
  }

  return {
    facingMode: { ideal: "environment" },
    width: { ideal: 1280 },
    height: { ideal: 720 },
    frameRate: { ideal: 12, max: 15 },
  };
}

function getFrameDimensions(video: HTMLVideoElement, maxLongEdge: number): {
  width: number;
  height: number;
} | null {
  const sourceWidth = Math.max(1, Math.floor(video.videoWidth || 0));
  const sourceHeight = Math.max(1, Math.floor(video.videoHeight || 0));
  if (!sourceWidth || !sourceHeight) {
    return null;
  }

  const longEdge = Math.max(sourceWidth, sourceHeight);
  const scale = longEdge > maxLongEdge ? maxLongEdge / longEdge : 1;
  return {
    width: Math.max(1, Math.round(sourceWidth * scale)),
    height: Math.max(1, Math.round(sourceHeight * scale)),
  };
}

function encodeVideoFrame(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement,
): string | null {
  const context = canvas.getContext("2d", {
    alpha: false,
    willReadFrequently: false,
  });
  if (!context) {
    return null;
  }

  for (const maxLongEdge of FRAME_MAX_LONG_EDGES) {
    const dimensions = getFrameDimensions(video, maxLongEdge);
    if (!dimensions) {
      return null;
    }

    canvas.width = dimensions.width;
    canvas.height = dimensions.height;
    context.drawImage(video, 0, 0, dimensions.width, dimensions.height);

    for (const quality of JPEG_QUALITIES) {
      const dataUrl = canvas.toDataURL("image/jpeg", quality);
      if (estimateDataUrlBytes(dataUrl) <= MAX_FRAME_BYTES) {
        return dataUrl;
      }
    }
  }

  return canvas.toDataURL("image/jpeg", JPEG_QUALITIES[JPEG_QUALITIES.length - 1]);
}

function isSyntheticCaptureState(state: RealtimeState): boolean {
  return state === "ready" || state === "listening";
}

export function useSyntheticRealtimeCamera({
  enabled,
  sessionState,
  sessionKey,
  turnBoundaryCount,
  sendJson,
  onError,
  messages,
}: UseSyntheticRealtimeCameraOptions): UseSyntheticRealtimeCameraReturn {
  const [isCameraSupported, setIsCameraSupported] = useState(false);
  const [isCameraEnabled, setIsCameraEnabled] = useState(false);
  const [isCameraActive, setIsCameraActive] = useState(false);
  const [previewStream, setPreviewStream] = useState<MediaStream | null>(null);
  const [videoDevices, setVideoDevices] = useState<RealtimeCameraDevice[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null);

  const streamRef = useRef<MediaStream | null>(null);
  const captureVideoRef = useRef<HTMLVideoElement | null>(null);
  const captureCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const frameIntervalRef = useRef<number | null>(null);
  const generationRef = useRef(0);
  const hasBufferedFramesRef = useRef(false);
  const turnBoundaryRef = useRef(turnBoundaryCount);
  const captureAllowedRef = useRef(enabled && isSyntheticCaptureState(sessionState));

  useEffect(() => {
    captureAllowedRef.current = enabled && isSyntheticCaptureState(sessionState);
  }, [enabled, sessionState]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    setIsCameraSupported(Boolean(enabled && navigator.mediaDevices?.getUserMedia));
    setSelectedDeviceId(window.localStorage.getItem(CAMERA_STORAGE_KEY));
  }, [enabled]);

  const refreshDevices = useCallback(async () => {
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.enumerateDevices) {
      return;
    }

    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const nextDevices = devices
        .filter((device) => device.kind === "videoinput")
        .map((device, index) => ({
          deviceId: device.deviceId,
          label: normalizeDeviceLabel(device, index),
        }));
      setVideoDevices(nextDevices);
      setSelectedDeviceId((currentValue) => {
        if (currentValue && nextDevices.some((device) => device.deviceId === currentValue)) {
          return currentValue;
        }

        const storedValue =
          typeof window !== "undefined"
            ? window.localStorage.getItem(CAMERA_STORAGE_KEY)
            : null;
        if (storedValue && nextDevices.some((device) => device.deviceId === storedValue)) {
          return storedValue;
        }

        return nextDevices[0]?.deviceId ?? currentValue ?? null;
      });
    } catch {
      // Best effort only.
    }
  }, []);

  const clearBufferedFrames = useCallback(() => {
    if (!hasBufferedFramesRef.current) {
      return;
    }
    hasBufferedFramesRef.current = false;
    sendJson({ type: "media.clear" });
  }, [sendJson]);

  const clearCurrentCamera = useCallback(() => {
    if (frameIntervalRef.current !== null) {
      window.clearInterval(frameIntervalRef.current);
      frameIntervalRef.current = null;
    }

    const captureVideo = captureVideoRef.current;
    if (captureVideo) {
      captureVideo.pause();
      captureVideo.srcObject = null;
    }

    stopTracks(streamRef.current);
    streamRef.current = null;
    setPreviewStream(null);
    setIsCameraActive(false);
  }, []);

  const captureAndSendFrame = useCallback(() => {
    if (!captureAllowedRef.current) {
      return;
    }

    const captureVideo = captureVideoRef.current;
    if (!captureVideo) {
      return;
    }

    if (!captureCanvasRef.current) {
      captureCanvasRef.current = document.createElement("canvas");
    }

    const dataUrl = encodeVideoFrame(captureVideo, captureCanvasRef.current);
    if (!dataUrl) {
      return;
    }

    hasBufferedFramesRef.current = true;
    sendJson({
      type: "media.frame.append",
      data_url: dataUrl,
      fps: SYNTHETIC_VIDEO_FPS,
    });
  }, [sendJson]);

  const startCamera = useCallback(async () => {
    if (!enabled || !isCameraEnabled || !isCameraSupported) {
      return;
    }

    const generation = generationRef.current + 1;
    generationRef.current = generation;
    clearCurrentCamera();

    let stream: MediaStream | null = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: buildVideoConstraints(selectedDeviceId),
      });
      if (generationRef.current !== generation) {
        stopTracks(stream);
        return;
      }

      streamRef.current = stream;
      setPreviewStream(stream);
      setIsCameraActive(true);

      if (!captureVideoRef.current) {
        const video = document.createElement("video");
        video.muted = true;
        video.autoplay = true;
        video.playsInline = true;
        captureVideoRef.current = video;
      }

      const captureVideo = captureVideoRef.current;
      captureVideo.srcObject = stream;
      const playAttempt = captureVideo.play().catch(() => undefined);
      if (captureVideo.readyState < HTMLMediaElement.HAVE_METADATA) {
        await new Promise<void>((resolve) => {
          const handleMetadata = () => resolve();
          captureVideo.addEventListener("loadedmetadata", handleMetadata, {
            once: true,
          });
        });
      }
      await playAttempt;

      await refreshDevices();
      const activeTrack = stream.getVideoTracks()[0];
      const activeDeviceId = String(activeTrack?.getSettings().deviceId || "").trim();
      if (activeDeviceId) {
        setSelectedDeviceId(activeDeviceId);
      }

      captureAndSendFrame();
      frameIntervalRef.current = window.setInterval(() => {
        captureAndSendFrame();
      }, FRAME_INTERVAL_MS);
    } catch {
      if (generationRef.current === generation) {
        clearCurrentCamera();
        setIsCameraEnabled(false);
        onError?.(
          messages?.cameraPermissionRequired ||
            messages?.cameraUnavailable ||
            "Camera permission is required",
        );
      }
      stopTracks(stream);
    }
  }, [
    captureAndSendFrame,
    clearCurrentCamera,
    enabled,
    isCameraEnabled,
    isCameraSupported,
    messages?.cameraPermissionRequired,
    messages?.cameraUnavailable,
    onError,
    refreshDevices,
    selectedDeviceId,
  ]);

  const stopCamera = useCallback(() => {
    generationRef.current += 1;
    clearCurrentCamera();
    clearBufferedFrames();
  }, [clearBufferedFrames, clearCurrentCamera]);

  const toggleCamera = useCallback(() => {
    if (!isCameraSupported) {
      onError?.(messages?.cameraUnavailable || "Camera access is not supported");
      return;
    }
    setIsCameraEnabled((currentValue) => !currentValue);
  }, [isCameraSupported, messages?.cameraUnavailable, onError]);

  const selectDevice = useCallback((deviceId: string) => {
    setSelectedDeviceId(deviceId || null);
  }, []);

  const cycleDevice = useCallback(() => {
    if (videoDevices.length < 2) {
      return;
    }

    setSelectedDeviceId((currentValue) => {
      const currentIndex = videoDevices.findIndex((device) => device.deviceId === currentValue);
      const nextIndex = currentIndex >= 0 ? (currentIndex + 1) % videoDevices.length : 0;
      return videoDevices[nextIndex]?.deviceId ?? currentValue ?? null;
    });
  }, [videoDevices]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    if (selectedDeviceId) {
      window.localStorage.setItem(CAMERA_STORAGE_KEY, selectedDeviceId);
    }
  }, [selectedDeviceId]);

  useEffect(() => {
    const refreshTimeout = window.setTimeout(() => {
      void refreshDevices();
    }, 0);
    if (!navigator.mediaDevices?.addEventListener) {
      return () => {
        window.clearTimeout(refreshTimeout);
      };
    }

    const handleDeviceChange = () => {
      void refreshDevices();
    };

    navigator.mediaDevices.addEventListener("devicechange", handleDeviceChange);
    return () => {
      window.clearTimeout(refreshTimeout);
      navigator.mediaDevices.removeEventListener("devicechange", handleDeviceChange);
    };
  }, [refreshDevices]);

  useEffect(() => {
    const stopTimeout = window.setTimeout(() => {
      stopCamera();
    }, 0);
    return () => {
      window.clearTimeout(stopTimeout);
    };
  }, [sessionKey, stopCamera]);

  useEffect(() => {
    if (turnBoundaryRef.current === turnBoundaryCount) {
      return;
    }
    turnBoundaryRef.current = turnBoundaryCount;
    hasBufferedFramesRef.current = false;
  }, [turnBoundaryCount]);

  useEffect(() => {
    if (!enabled || !isCameraEnabled) {
      const stopTimeout = window.setTimeout(() => {
        stopCamera();
      }, 0);
      return () => {
        window.clearTimeout(stopTimeout);
      };
    }

    let cancelled = false;
    const startTimeout = window.setTimeout(() => {
      if (!cancelled) {
        void startCamera();
      }
    }, 0);
    return () => {
      cancelled = true;
      window.clearTimeout(startTimeout);
      stopCamera();
    };
  }, [enabled, isCameraEnabled, selectedDeviceId, startCamera, stopCamera]);

  return {
    isCameraSupported,
    isCameraEnabled,
    isCameraActive,
    previewStream,
    videoDevices,
    selectedDeviceId,
    toggleCamera,
    selectDevice,
    cycleDevice,
  };
}
