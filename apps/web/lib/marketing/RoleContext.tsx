"use client";

import { createContext, useContext, useEffect, useRef, type ReactNode } from "react";
import { useRoleSelection, type UseRoleSelection } from "@/hooks/useRoleSelection";
import type { RoleKey } from "@/lib/marketing/role-content";
import { emitLandingEvent } from "@/lib/marketing/analytics";

const RoleContext = createContext<UseRoleSelection | null>(null);

interface RoleProviderProps {
  initialRole: RoleKey | null;
  locale: "zh" | "en";
  children: ReactNode;
}

export function RoleProvider({ initialRole, locale, children }: RoleProviderProps) {
  const api = useRoleSelection(initialRole);
  const emittedRestoredRef = useRef(false);

  // Fire landing.role.restored once on mount when initialRole came from SSR
  // cookie (true "restored from last visit"). This is NOT the same as a user
  // picking a role for the first time (that's landing.role.selected).
  useEffect(() => {
    if (!emittedRestoredRef.current && initialRole) {
      emittedRestoredRef.current = true;
      emitLandingEvent("landing.role.restored", { role: initialRole, locale });
    }
    // Only intended to fire on mount. Guarded by the ref flag.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <RoleContext.Provider value={api}>{children}</RoleContext.Provider>;
}

export function useRoleContext(): UseRoleSelection {
  const ctx = useContext(RoleContext);
  if (!ctx) {
    throw new Error("useRoleContext must be used inside <RoleProvider>");
  }
  return ctx;
}
