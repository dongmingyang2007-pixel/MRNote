"use client";

import { useCallback, useEffect, useState } from "react";
import { clearCookie, readCookie, writeCookie } from "@/lib/cookie";
import { ROLE_KEYS, type RoleKey } from "@/lib/marketing/role-content";

export const ROLE_COOKIE_NAME = "mrai_landing_role";
const THIRTY_DAYS_SECONDS = 60 * 60 * 24 * 30;

function readRoleFromCookie(): RoleKey | null {
  const raw = readCookie(ROLE_COOKIE_NAME);
  if (!raw) return null;
  return (ROLE_KEYS as readonly string[]).includes(raw) ? (raw as RoleKey) : null;
}

export interface UseRoleSelection {
  role: RoleKey | null;
  setRole: (next: RoleKey) => void;
  clearRole: () => void;
}

export function useRoleSelection(initialRole: RoleKey | null): UseRoleSelection {
  const [role, setRoleState] = useState<RoleKey | null>(initialRole ?? null);

  // Reconcile with the live cookie once after mount. SSR may have computed a
  // stale initialRole (user cleared the cookie in devtools, multi-tab, etc.).
  // Initializing from the prop (not the cookie) keeps server + client renders
  // identical and avoids React hydration warnings.
  useEffect(() => {
    const live = readRoleFromCookie();
    if (live !== role) {
      setRoleState(live ?? initialRole ?? null);
    }
    // Only reconcile once on mount. setRole / clearRole take over afterwards.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setRole = useCallback((next: RoleKey) => {
    setRoleState((prev) => {
      if (prev === next) return prev;
      writeCookie(ROLE_COOKIE_NAME, next, THIRTY_DAYS_SECONDS);
      return next;
    });
  }, []);

  const clearRole = useCallback(() => {
    clearCookie(ROLE_COOKIE_NAME);
    setRoleState(null);
  }, []);

  return { role, setRole, clearRole };
}
