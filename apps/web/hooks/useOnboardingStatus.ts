"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { dispatchNotebooksChanged } from "@/lib/notebook-events";
import { readCookie } from "@/lib/cookie";

export const ONBOARDING_COMPLETION_KEY_PREFIX = "mrnote_onboarding_completed";
const LEGACY_LS_KEY = "mrnote_onboarding_completed";
const WORKSPACE_COOKIE_NAME = "mingrun_workspace_id";
const LEGACY_WORKSPACE_COOKIE_NAME = "qihang_workspace_id";

type MeResponse = {
  id: string;
  onboarding_completed_at?: string | null;
};

function getWorkspaceId(): string | null {
  return readCookie(WORKSPACE_COOKIE_NAME) || readCookie(LEGACY_WORKSPACE_COOKIE_NAME);
}

export function getScopedOnboardingKey(
  userId: string,
  workspaceId: string | null,
): string {
  return `${ONBOARDING_COMPLETION_KEY_PREFIX}:${workspaceId || "no-workspace"}:${userId}`;
}

/**
 * Returns whether the current user has completed the 5-step onboarding
 * wizard. We verify the current user first, then read/write a localStorage
 * cache scoped to that user + workspace. This avoids leaking completion
 * state across account or workspace switches in the same browser.
 *
 * If the server call fails (e.g., offline), we fall back to the
 * safest value (`false`) because we can't reliably identify which user
 * should own a cached onboarding flag.
 */
export function useOnboardingStatus() {
  const [completed, setCompleted] = useState<boolean | null>(null);
  const scopedKeyRef = useRef<string | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;

    window.localStorage.removeItem(LEGACY_LS_KEY);

    let cancelled = false;
    (async () => {
      try {
        const { apiGet } = await import("@/lib/api");
        const me = await apiGet<MeResponse>("/api/v1/auth/me");
        if (cancelled) return;

        const scopedKey = getScopedOnboardingKey(me.id, getWorkspaceId());
        scopedKeyRef.current = scopedKey;
        const cached = window.localStorage.getItem(scopedKey) === "1";

        if (cached || me.onboarding_completed_at) {
          window.localStorage.setItem(scopedKey, "1");
          setCompleted(true);
        } else {
          setCompleted(false);
        }
      } catch {
        if (!cancelled) setCompleted(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const markCompleted = useCallback(async () => {
    if (typeof window !== "undefined") {
      if (scopedKeyRef.current) {
        window.localStorage.setItem(scopedKeyRef.current, "1");
      }
      window.localStorage.removeItem(LEGACY_LS_KEY);
    }
    setCompleted(true);
    dispatchNotebooksChanged();
    try {
      const { apiPost } = await import("@/lib/api");
      await apiPost("/api/v1/auth/onboarding/complete", {});
    } catch {
      // Server failure does not block — user is through the wizard.
    }
  }, []);

  return { completed, markCompleted };
}
