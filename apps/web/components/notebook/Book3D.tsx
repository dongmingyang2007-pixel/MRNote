"use client";

import type { CSSProperties } from "react";

export interface Book3DProps {
  title: string;
  typeLabel: string;
  baseColor: string;
  midColor: string;
  shadowColor: string;
  foilColor: string;
  bookmarkColor: string;
  isOpening?: boolean;
}

/**
 * Lightweight CSS-only book card. The 3D look is done via CSS transforms
 * and gradients — no WebGL, no R3F dependencies. Animations are limited to
 * a hover lift and an open keyframe driven by `data-opening`.
 */
export function Book3D({
  title,
  typeLabel,
  baseColor,
  midColor,
  shadowColor,
  foilColor,
  bookmarkColor,
  isOpening,
}: Book3DProps) {
  const style = {
    "--book-base": baseColor,
    "--book-mid": midColor,
    "--book-shadow": shadowColor,
    "--book-foil": foilColor,
    "--book-bookmark": bookmarkColor,
  } as CSSProperties;

  return (
    <div
      className="book3d"
      data-opening={isOpening || undefined}
      style={style}
    >
      <div className="book3d__stage">
        <div className="book3d__spine" aria-hidden="true">
          <span className="book3d__spine-title">{title}</span>
        </div>
        <div className="book3d__cover">
          <span className="book3d__type">{typeLabel}</span>
          <span className="book3d__title">{title}</span>
          <span className="book3d__rule" aria-hidden="true" />
        </div>
      </div>
    </div>
  );
}

