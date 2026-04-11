import { DEFAULT_LOCAL_API_PORT, LOCAL_BIND_HOSTS, isLoopbackHost } from "@/lib/network-hosts";

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

function shouldUseDirectBrowserApi(configured?: string): boolean {
  if (!configured) {
    return false;
  }

  try {
    const url = new URL(configured);
    return isLoopbackHost(url.hostname) || LOCAL_BIND_HOSTS.has(url.hostname);
  } catch {
    return false;
  }
}

export function getApiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();

  if (typeof window === "undefined") {
    return trimTrailingSlash(configured || `http://localhost:${DEFAULT_LOCAL_API_PORT}`);
  }

  const current = new URL(window.location.href);
  const fallback = `${current.protocol}//${current.hostname}:${DEFAULT_LOCAL_API_PORT}`;
  if (!configured) {
    return trimTrailingSlash(fallback);
  }

  try {
    const configuredUrl = new URL(configured);
    if (LOCAL_BIND_HOSTS.has(configuredUrl.hostname)) {
      configuredUrl.hostname = isLoopbackHost(current.hostname) ? current.hostname : "localhost";
      return trimTrailingSlash(configuredUrl.toString());
    }
    if (isLoopbackHost(current.hostname) && isLoopbackHost(configuredUrl.hostname) && current.hostname !== configuredUrl.hostname) {
      configuredUrl.hostname = current.hostname;
      return trimTrailingSlash(configuredUrl.toString());
    }
  } catch {
    return trimTrailingSlash(configured);
  }

  return trimTrailingSlash(configured);
}

export function getApiHttpBaseUrl(): string {
  if (typeof window !== "undefined") {
    const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
    if (shouldUseDirectBrowserApi(configured)) {
      return getApiBaseUrl();
    }
    return "";
  }
  return getApiBaseUrl();
}

export const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME ?? "铭润科技";
