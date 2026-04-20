"use client";

import { useCallback, useState } from "react";
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
  const [role, setRoleState] = useState<RoleKey | null>(() => {
    // In browser, prefer live cookie over stale SSR hint.
    if (typeof document !== "undefined") {
      return readRoleFromCookie() ?? initialRole ?? null;
    }
    return initialRole ?? null;
  });

  const setRole = useCallback((next: RoleKey) => {
    writeCookie(ROLE_COOKIE_NAME, next, THIRTY_DAYS_SECONDS);
    setRoleState(next);
  }, []);

  const clearRole = useCallback(() => {
    clearCookie(ROLE_COOKIE_NAME);
    setRoleState(null);
  }, []);

  return { role, setRole, clearRole };
}
