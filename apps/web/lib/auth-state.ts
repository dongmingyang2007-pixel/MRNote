import { readCookie, writeCookie, clearCookie } from "@/lib/cookie";

const AUTH_STATE_COOKIE = "auth_state";
const AUTH_STATE_EVENT = "auth-state-change";

function emitAuthStateChange(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(AUTH_STATE_EVENT));
}

export function isLoggedIn(): boolean {
  return readCookie(AUTH_STATE_COOKIE) === "1";
}

export function subscribeAuthState(onStoreChange: () => void): () => void {
  if (typeof window === "undefined") {
    return () => {};
  }
  window.addEventListener(AUTH_STATE_EVENT, onStoreChange);
  return () => window.removeEventListener(AUTH_STATE_EVENT, onStoreChange);
}

export function getAuthStateSnapshot(): boolean {
  return isLoggedIn();
}

export function getAuthStateServerSnapshot(): boolean {
  return false;
}

export function setAuthState(maxAgeSeconds?: number): void {
  writeCookie(AUTH_STATE_COOKIE, "1", maxAgeSeconds);
  emitAuthStateChange();
}

export function clearAuthState(): void {
  clearCookie(AUTH_STATE_COOKIE);
  emitAuthStateChange();
}
