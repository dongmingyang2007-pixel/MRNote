"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { clearCookie, readCookie, writeCookie } from "@/lib/cookie";
import { ROLE_KEYS, type RoleKey } from "@/lib/marketing/role-content";
import { apiGet, apiPatch, isApiRequestError } from "@/lib/api";
import { isPersonaKey, type PersonaKey } from "@/lib/persona";
import { emitLandingEvent } from "@/lib/marketing/analytics";

export const ROLE_COOKIE_NAME = "mrai_landing_role";
export const PERSONA_COOKIE_NAME = "mrai_persona";
const THIRTY_DAYS_SECONDS = 60 * 60 * 24 * 30;

// 300ms matches spec §2.5's "avoid chattering PATCH on quick pill clicks".
const PERSONA_PATCH_DEBOUNCE_MS = 300;

function readRoleFromCookie(): RoleKey | null {
  const raw = readCookie(ROLE_COOKIE_NAME);
  if (!raw) return null;
  return (ROLE_KEYS as readonly string[]).includes(raw) ? (raw as RoleKey) : null;
}

function readPersonaFromCookie(): PersonaKey | null {
  const raw = readCookie(PERSONA_COOKIE_NAME);
  return isPersonaKey(raw) ? raw : null;
}

export interface UseRoleSelection {
  role: RoleKey | null;
  setRole: (next: RoleKey) => void;
  clearRole: () => void;
  /** Server-synced user identity ("student" / "researcher" / "pm"). Null for
   *  guests or signed-in users who never set it. */
  persona: PersonaKey | null;
  /** Persist a new persona. Server-synced when logged in (PATCH /me); cookie
   *  kept as the authoritative cache. Debounced to 300ms. */
  setPersona: (next: PersonaKey | null) => void;
}

interface AuthMe {
  id: string;
  email: string;
  persona?: PersonaKey | null;
}

/** Best-effort: probe `/api/v1/auth/me` and return `null` on any failure.
 *  401 is the common "guest" case — we purposely don't let apiGet's global
 *  unauthorized-redirect fire (marketing page is public). Other errors are
 *  silent; persona sync is a UX enhancement, not a correctness path. */
async function probeAuthMe(): Promise<AuthMe | null> {
  try {
    return await apiGet<AuthMe>("/api/v1/auth/me", undefined, {
      suppressUnauthorizedHandling: true,
    });
  } catch {
    return null;
  }
}

/** PATCH the server's persona field. Returns true on success, false on any
 *  failure (including backend not-yet-deployed 404 / 405). Caller still
 *  persists locally either way — the cookie is the fallback. */
async function patchPersona(value: PersonaKey | null): Promise<boolean> {
  try {
    await apiPatch<unknown>("/api/v1/auth/me", { persona: value });
    return true;
  } catch (err) {
    // 404 / 405 = endpoint not deployed yet; 401 = guest; all soft-fail.
    if (isApiRequestError(err)) {
      return false;
    }
    return false;
  }
}

export function useRoleSelection(initialRole: RoleKey | null): UseRoleSelection {
  const [role, setRoleState] = useState<RoleKey | null>(initialRole ?? null);
  const [persona, setPersonaState] = useState<PersonaKey | null>(null);

  // Track logged-in status once probed — decides whether setPersona should
  // PATCH the server. Null = not yet probed (or guest).
  const isLoggedInRef = useRef<boolean>(false);
  const patchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingPatchRef = useRef<PersonaKey | null | undefined>(undefined);

  // Reconcile with the live cookie once after mount. SSR may have computed a
  // stale initialRole (user cleared the cookie in devtools, multi-tab, etc.).
  // Initializing from the prop (not the cookie) keeps server + client renders
  // identical and avoids React hydration warnings.
  useEffect(() => {
    const live = readRoleFromCookie();
    if (live !== role) {
      setRoleState(live ?? initialRole ?? null);
    }

    // Seed persona from cookie synchronously so first paint of the settings
    // page or homepage badge reflects the cached identity. The server probe
    // below may overwrite it.
    const cookiePersona = readPersonaFromCookie();
    if (cookiePersona) {
      setPersonaState(cookiePersona);
    }

    // Fire-and-forget server sync. We intentionally do not `await` so the
    // homepage doesn't block first paint on /auth/me latency.
    void (async () => {
      const me = await probeAuthMe();
      if (!me) {
        isLoggedInRef.current = false;
        return;
      }
      isLoggedInRef.current = true;

      const serverPersona: PersonaKey | null = isPersonaKey(me.persona)
        ? me.persona
        : null;

      if (serverPersona) {
        // Server value wins: overwrite local cache + React state.
        setPersonaState(serverPersona);
        writeCookie(PERSONA_COOKIE_NAME, serverPersona, THIRTY_DAYS_SECONDS);
        emitLandingEvent("landing.persona.server_synced", {
          persona: serverPersona,
          direction: "server_to_local",
        });
      } else if (cookiePersona) {
        // Server null but local cached — merge local into account.
        const ok = await patchPersona(cookiePersona);
        if (ok) {
          emitLandingEvent("landing.persona.server_synced", {
            persona: cookiePersona,
            direction: "local_to_server",
          });
        }
      }
    })();

    // Only reconcile once on mount. setRole / clearRole / setPersona take
    // over afterwards.
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

  const setPersona = useCallback((next: PersonaKey | null) => {
    setPersonaState(next);
    if (next) {
      writeCookie(PERSONA_COOKIE_NAME, next, THIRTY_DAYS_SECONDS);
    } else {
      clearCookie(PERSONA_COOKIE_NAME);
    }

    // Debounce the PATCH: rapid pill clicks only send the last value.
    pendingPatchRef.current = next;
    if (patchTimerRef.current) {
      clearTimeout(patchTimerRef.current);
    }
    patchTimerRef.current = setTimeout(() => {
      patchTimerRef.current = null;
      // Only PATCH when we know the user is logged in. Guests store the
      // persona cookie-only — the next login merge (mount-time flow above)
      // will promote it to the server.
      if (!isLoggedInRef.current) {
        return;
      }
      const value = pendingPatchRef.current;
      pendingPatchRef.current = undefined;
      void patchPersona(value ?? null).then((ok) => {
        if (ok) {
          emitLandingEvent("landing.persona.server_synced", {
            persona: value ?? null,
            direction: "local_to_server",
          });
        }
      });
    }, PERSONA_PATCH_DEBOUNCE_MS);
  }, []);

  // Cleanup any pending timer on unmount so we don't leak a trailing PATCH.
  useEffect(() => {
    return () => {
      if (patchTimerRef.current) {
        clearTimeout(patchTimerRef.current);
        patchTimerRef.current = null;
      }
    };
  }, []);

  return { role, setRole, clearRole, persona, setPersona };
}
