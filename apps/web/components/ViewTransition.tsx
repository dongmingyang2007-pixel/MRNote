"use client";

import type { ReactNode } from "react";

/**
 * Route transitions are intentionally left to Next.js.
 *
 * The previous Chrome-only enhancement made navigation feel slower than Safari
 * because only browsers exposing View Transitions received an extra fade step.
 */
export function ViewTransition({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
