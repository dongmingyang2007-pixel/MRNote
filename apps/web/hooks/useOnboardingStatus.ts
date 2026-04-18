"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const LS_KEY = "mrnote_onboarding_completed";

type MeResponse = {
  onboarding_completed_at?: string | null;
};

/**
 * Returns whether the current user has completed the 5-step onboarding
 * wizard. Checks localStorage first (fast path — avoids showing the
 * modal for a frame on every workspace navigation), then verifies with
 * the server via GET /api/v1/auth/me.
 *
 * If the server call fails (e.g., offline), we fall back to the
 * localStorage value. The markCompleted() call persists both locally
 * and to the server via POST /api/v1/auth/onboarding/complete. API
 * failures do not block the UI — localStorage always wins.
 */
export function useOnboardingStatus() {
  const [completed, setCompleted] = useState<boolean | null>(null);
  const verified = useRef(false);

  useEffect(() => {
    if (typeof window === "undefined") return;

    // Fast path: cached in localStorage.
    const cached = window.localStorage.getItem(LS_KEY);
    if (cached === "1") {
      setCompleted(true);
      return;
    }

    // Otherwise check server (new user or cleared localStorage).
    if (verified.current) return;
    verified.current = true;

    let cancelled = false;
    (async () => {
      try {
        const { apiGet } = await import("@/lib/api");
        const me = await apiGet<MeResponse>("/api/v1/auth/me");
        if (cancelled) return;
        if (me.onboarding_completed_at) {
          window.localStorage.setItem(LS_KEY, "1");
          setCompleted(true);
        } else {
          setCompleted(false);
        }
      } catch {
        // Network / auth failure — assume not completed so the wizard
        // can still show for fresh users. An authenticated user who
        // briefly loses connectivity and already finished onboarding
        // has the LS key, so they would have hit the fast path above.
        if (!cancelled) setCompleted(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const markCompleted = useCallback(async () => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(LS_KEY, "1");
    }
    setCompleted(true);
    try {
      const { apiPost } = await import("@/lib/api");
      await apiPost("/api/v1/auth/onboarding/complete", {});
    } catch {
      // Server failure does not block — user is through the wizard.
    }
  }, []);

  return { completed, markCompleted };
}
