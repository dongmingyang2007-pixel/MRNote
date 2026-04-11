import { buildClientCookieAttributes } from "@/lib/security";

export function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie
    .split(";")
    .map((c) => c.trim())
    .find((c) => c.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split("=").slice(1).join("=")) : null;
}

export function writeCookie(name: string, value: string, maxAge?: number): void {
  if (typeof document === "undefined") return;
  document.cookie = `${name}=${encodeURIComponent(value)}; ${buildClientCookieAttributes(maxAge)}`;
}

export function clearCookie(name: string): void {
  if (typeof document === "undefined") return;
  document.cookie = `${name}=; ${buildClientCookieAttributes(0)}`;
}
