/**
 * Shared Framer Motion configuration.
 * Mirrors the CSS duration/easing tokens in globals.css for consistency.
 */

export const duration = {
  fast: 0.1,
  normal: 0.2,
  slow: 0.35,
} as const;

export const ease = {
  out: [0.16, 1, 0.3, 1] as const,
  inOut: [0.65, 0, 0.35, 1] as const,
  spring: { type: "spring" as const, stiffness: 400, damping: 25 },
} as const;

/** Standard page enter transition */
export const pageEnter = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: duration.normal, ease: ease.out },
} as const;

/** Stagger children in a list */
export const staggerContainer = {
  animate: { transition: { staggerChildren: 0.03 } },
} as const;

/** Single list item entrance */
export const staggerItem = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0, transition: { duration: duration.normal, ease: ease.out } },
} as const;

/** Crossfade between skeleton and content */
export const crossfade = {
  initial: { opacity: 0 },
  animate: { opacity: 1, transition: { duration: duration.normal } },
  exit: { opacity: 0, transition: { duration: duration.fast } },
} as const;

/** Command palette / dialog entrance */
export const dialogEnter = {
  initial: { opacity: 0, scale: 0.95 },
  animate: { opacity: 1, scale: 1, transition: { duration: duration.normal, ease: ease.out } },
  exit: { opacity: 0, scale: 0.95, transition: { duration: duration.fast } },
} as const;
