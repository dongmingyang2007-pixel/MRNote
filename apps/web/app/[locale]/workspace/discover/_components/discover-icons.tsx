import type { ComponentType } from "react";

/**
 * Custom SVG icons for the Discover page.
 * No emoji — all icons are original vector art.
 */

interface IconProps {
  size?: number;
  className?: string;
}

export function SearchIcon({ size = 18, className }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      className={className}
    >
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20 16.65 16.65" />
    </svg>
  );
}

export function ArrowRightIcon({ size = 14, className }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M5 12h14" />
      <path d="m13 6 6 6-6 6" />
    </svg>
  );
}

export function HeartIcon({ size = 12, className }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className={className}
    >
      <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78L12 21.23l8.84-8.84a5.5 5.5 0 0 0 0-7.78z" />
    </svg>
  );
}

export function DownloadIcon({ size = 12, className }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  );
}

export function UserAvatarIcon({ size = 18, className }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <circle cx="12" cy="8.5" r="3.2" />
      <path d="M5 19c1.8-3.1 4.2-4.6 7-4.6S17.2 15.9 19 19" />
    </svg>
  );
}

/* ------------------------------------------------------------------ */
/*  Scene navigation icons — one per pipeline_slot                    */
/* ------------------------------------------------------------------ */

export function SceneLlmIcon({ size = 24 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" fill="none">
      <path
        d="M5 7h18M5 12h14M5 17h10M5 22h16"
        stroke="white"
        strokeWidth="1.8"
        strokeLinecap="round"
        opacity="0.8"
      />
      <path d="M22 14l-2 10 3-3 3 3-2-10" fill="white" opacity="0.85" />
    </svg>
  );
}

export function SceneAsrIcon({ size = 24 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" fill="none">
      <rect
        x="11"
        y="3"
        width="6"
        height="12"
        rx="3"
        fill="white"
        opacity="0.9"
      />
      <path
        d="M8 12a6 6 0 0 0 12 0"
        stroke="white"
        strokeWidth="1.8"
        strokeLinecap="round"
        opacity="0.7"
      />
      <line
        x1="14"
        y1="18"
        x2="14"
        y2="22"
        stroke="white"
        strokeWidth="1.8"
        strokeLinecap="round"
        opacity="0.6"
      />
    </svg>
  );
}

export function SceneTtsIcon({ size = 24 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" fill="none">
      <path d="M4 11v6l6 5V6l-6 5z" fill="white" opacity="0.9" />
      <path
        d="M15 9a5 5 0 0 1 0 10"
        stroke="white"
        strokeWidth="1.8"
        strokeLinecap="round"
        opacity="0.7"
      />
      <path
        d="M18 6a9 9 0 0 1 0 16"
        stroke="white"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.4"
      />
    </svg>
  );
}

export function SceneVisionIcon({ size = 24 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" fill="none">
      <circle
        cx="14"
        cy="14"
        r="5"
        stroke="white"
        strokeWidth="1.8"
        opacity="0.9"
      />
      <circle cx="14" cy="14" r="2" fill="white" opacity="0.9" />
      <path
        d="M2 14s5-9 12-9 12 9 12 9-5 9-12 9-12-9-12-9z"
        stroke="white"
        strokeWidth="1.5"
        opacity="0.5"
        fill="none"
      />
    </svg>
  );
}

export function SceneRealtimeIcon({ size = 24 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" fill="none">
      <circle
        cx="14"
        cy="14"
        r="10"
        stroke="white"
        strokeWidth="1.5"
        opacity="0.5"
      />
      <circle
        cx="14"
        cy="14"
        r="5"
        stroke="white"
        strokeWidth="1.8"
        opacity="0.8"
      />
      <circle cx="14" cy="14" r="1.5" fill="white" opacity="0.9" />
    </svg>
  );
}

export function SceneRealtimeAsrIcon({ size = 24 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" fill="none">
      <rect
        x="11"
        y="5"
        width="5"
        height="10"
        rx="2.5"
        fill="white"
        opacity="0.85"
      />
      <path
        d="M9 13a5 5 0 0 0 10 0"
        stroke="white"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.6"
      />
      <circle
        cx="22"
        cy="8"
        r="4"
        stroke="white"
        strokeWidth="1.5"
        opacity="0.5"
      />
      <path
        d="M20.5 8h3M22 6.5v3"
        stroke="white"
        strokeWidth="1"
        strokeLinecap="round"
        opacity="0.7"
      />
    </svg>
  );
}

export function SceneRealtimeTtsIcon({ size = 24 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" fill="none">
      <path d="M5 11v6l5 4V7l-5 4z" fill="white" opacity="0.85" />
      <path
        d="M14 10a4 4 0 0 1 0 8"
        stroke="white"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.6"
      />
      <circle
        cx="22"
        cy="8"
        r="4"
        stroke="white"
        strokeWidth="1.5"
        opacity="0.5"
      />
      <path
        d="M20.5 8h3M22 6.5v3"
        stroke="white"
        strokeWidth="1"
        strokeLinecap="round"
        opacity="0.7"
      />
    </svg>
  );
}

/** Maps pipeline_slot → icon component */
export const SCENE_ICON_MAP: Record<string, ComponentType<IconProps>> = {
  llm: SceneLlmIcon,
  asr: SceneAsrIcon,
  tts: SceneTtsIcon,
  vision: SceneVisionIcon,
  realtime: SceneRealtimeIcon,
  realtime_asr: SceneRealtimeAsrIcon,
  realtime_tts: SceneRealtimeTtsIcon,
};

/** Maps pipeline_slot → gradient CSS value */
export const SCENE_GRADIENT_MAP: Record<string, string> = {
  llm: "linear-gradient(135deg, #6366f1, #8b5cf6)",
  asr: "linear-gradient(135deg, #3b82f6, #60a5fa)",
  tts: "linear-gradient(135deg, #06b6d4, #22d3ee)",
  vision: "linear-gradient(135deg, #f59e0b, #fbbf24)",
  realtime: "linear-gradient(135deg, #10b981, #34d399)",
  realtime_asr: "linear-gradient(135deg, #8b5cf6, #a78bfa)",
  realtime_tts: "linear-gradient(135deg, #ec4899, #f472b6)",
};

export const SCENE_ACCENT_MAP: Record<string, string> = {
  llm: "#8b5cf6",
  asr: "#60a5fa",
  tts: "#22d3ee",
  vision: "#f59e0b",
  realtime: "#34d399",
  realtime_asr: "#a78bfa",
  realtime_tts: "#f472b6",
};

/* ------------------------------------------------------------------ */
/*  Category icons                                                    */
/* ------------------------------------------------------------------ */

export function CategoryTextIcon({ size = 16, className }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      className={className}
    >
      <path
        d="M5 7h14M5 12h14M5 17h10"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function CategorySparkIcon({ size = 16, className }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      className={className}
    >
      <path
        d="M12 3l1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6L12 3z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path
        d="M18.5 15.5l.7 1.9 1.8.7-1.8.7-.7 1.9-.7-1.9-1.8-.7 1.8-.7.7-1.9z"
        fill="currentColor"
      />
    </svg>
  );
}

export function CategoryVisionIcon({ size = 16, className }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      className={className}
    >
      <circle cx="12" cy="12" r="2.5" fill="currentColor" />
      <path
        d="M3 12s3.8-5.5 9-5.5S21 12 21 12s-3.8 5.5-9 5.5S3 12 3 12z"
        stroke="currentColor"
        strokeWidth="1.6"
      />
    </svg>
  );
}

export function CategoryAudioIcon({ size = 16, className }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      className={className}
    >
      <path d="M4 10v4l4 3V7l-4 3z" fill="currentColor" />
      <path
        d="M13 9a4 4 0 0 1 0 6"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <path
        d="M16 6a8 8 0 0 1 0 12"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        opacity="0.7"
      />
    </svg>
  );
}

export function CategoryRealtimeIcon({ size = 16, className }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      className={className}
    >
      <circle
        cx="12"
        cy="12"
        r="7"
        stroke="currentColor"
        strokeWidth="1.6"
        opacity="0.6"
      />
      <circle cx="12" cy="12" r="3.5" stroke="currentColor" strokeWidth="1.8" />
      <circle cx="12" cy="12" r="1.4" fill="currentColor" />
    </svg>
  );
}

export function CategoryRankIcon({ size = 16, className }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      className={className}
    >
      <path
        d="M6 17V8M12 17V5M18 17v-6"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function categoryIconForKey(key: string): ComponentType<IconProps> {
  if (
    key.includes("vision") ||
    key.includes("image") ||
    key.includes("video")
  ) {
    return CategoryVisionIcon;
  }
  if (key.includes("speech") || key.includes("tts") || key.includes("asr")) {
    return CategoryAudioIcon;
  }
  if (key.includes("realtime")) {
    return CategoryRealtimeIcon;
  }
  if (key.includes("rerank")) {
    return CategoryRankIcon;
  }
  if (
    key.includes("thinking") ||
    key.includes("omni") ||
    key.includes("embedding")
  ) {
    return CategorySparkIcon;
  }
  return CategoryTextIcon;
}

/* ------------------------------------------------------------------ */
/*  Decorative SVG patterns for featured model cards                  */
/* ------------------------------------------------------------------ */

export function DecoCircles() {
  return (
    <svg
      width="70"
      height="70"
      viewBox="0 0 70 70"
      fill="none"
      style={{ position: "absolute", top: 10, right: 10, opacity: 0.12 }}
    >
      <circle cx="35" cy="35" r="30" stroke="white" strokeWidth="2" />
      <circle cx="35" cy="35" r="18" stroke="white" strokeWidth="1.5" />
      <circle cx="35" cy="35" r="7" fill="white" />
    </svg>
  );
}

export function DecoWave() {
  return (
    <svg
      width="50"
      height="50"
      viewBox="0 0 50 50"
      fill="none"
      style={{ position: "absolute", top: 10, right: 10, opacity: 0.12 }}
    >
      <path
        d="M8 38C8 20 22 10 38 10"
        stroke="white"
        strokeWidth="3"
        strokeLinecap="round"
      />
      <path d="M8 38C8 24 28 14 42 18" stroke="white" strokeWidth="2" />
      <circle cx="8" cy="38" r="3" fill="white" />
    </svg>
  );
}

export function DecoLandscape() {
  return (
    <svg
      width="50"
      height="50"
      viewBox="0 0 50 50"
      fill="none"
      style={{ position: "absolute", top: 10, right: 10, opacity: 0.12 }}
    >
      <rect
        x="5"
        y="8"
        width="40"
        height="34"
        rx="4"
        stroke="white"
        strokeWidth="2"
      />
      <circle cx="18" cy="22" r="5" stroke="white" strokeWidth="1.5" />
      <path d="M5 35l12-10 8 6 10-12 10 16" stroke="white" strokeWidth="1.5" />
    </svg>
  );
}
