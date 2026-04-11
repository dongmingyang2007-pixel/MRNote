"use client";

import type { CSSProperties } from "react";

import { SCENE_ACCENT_MAP, SCENE_ICON_MAP } from "./discover-icons";
import { sceneLabel } from "@/lib/discover-labels";

interface DiscoverSceneNavProps {
  /** pipeline_slot values that have at least one model in the catalog */
  activeSlots: string[];
  /** slots that match the current search context */
  matchingSlots: Set<string>;
  /** Currently selected slot (from URL ?slot=xxx), or null */
  selectedSlot: string | null;
  /** Callback when a scene card is clicked */
  onSelect: (slot: string | null) => void;
  /** i18n translate function scoped to "console" */
  t: (key: string) => string;
  sectionLabel: string;
}

/** Canonical display order for pipeline slots */
const SLOT_ORDER: string[] = [
  "llm",
  "asr",
  "tts",
  "vision",
  "realtime",
  "realtime_asr",
  "realtime_tts",
];

export function DiscoverSceneNav({
  activeSlots,
  matchingSlots,
  selectedSlot,
  onSelect,
  t,
  sectionLabel,
}: DiscoverSceneNavProps) {
  const slotsToShow = SLOT_ORDER.filter((slot) => activeSlots.includes(slot));

  if (slotsToShow.length === 0) {
    return null;
  }

  return (
    <div className="dhub-scenes">
      <div className="dhub-scenes-label">{sectionLabel}</div>
      <div className="dhub-scenes-grid">
        {slotsToShow.map((slot, index) => {
          const Icon = SCENE_ICON_MAP[slot];
          const accent = SCENE_ACCENT_MAP[slot] || "#94a3b8";
          const isSelected = selectedSlot === slot;
          const isMatching = matchingSlots.has(slot);
          const cardStyle = {
            "--scene-accent": accent,
          } as CSSProperties;

          return (
            <button
              key={slot}
              type="button"
              aria-pressed={isSelected}
              className={`dhub-scene-card${isSelected ? " is-active" : ""}${!isMatching ? " is-dimmed" : ""}`}
              style={cardStyle}
              onClick={() => onSelect(isSelected ? null : slot)}
            >
              <span className="dhub-scene-card-top">
                {Icon ? <Icon size={20} /> : null}
                <span className="dhub-scene-card-index">
                  {String(index + 1).padStart(2, "0")}
                </span>
              </span>
              <span className="dhub-scene-card-name">
                {sceneLabel(slot, t)}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
