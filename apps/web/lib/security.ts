const DEFAULT_ALLOWED_PROTOCOLS = new Set(["http:", "https:", "blob:"]);
const IMAGE_ALLOWED_PROTOCOLS = new Set(["http:", "https:", "blob:", "data:"]);

function getWindowOrigin(): string {
  if (typeof window === "undefined") {
    return "http://localhost";
  }
  return window.location.origin;
}

export function shouldUseSecureClientCookie(): boolean {
  return typeof window !== "undefined" && window.location.protocol === "https:";
}

export function buildClientCookieAttributes(maxAge?: number): string {
  let attributes = "Path=/; SameSite=Lax";
  if (maxAge !== undefined) {
    attributes += `; Max-Age=${maxAge}`;
  }
  if (shouldUseSecureClientCookie()) {
    attributes += "; Secure";
  }
  return attributes;
}

export function getSafeNavigationPath(value?: string | null): string | null {
  if (!value || typeof window === "undefined") {
    return null;
  }

  try {
    const url = new URL(value, window.location.origin);
    if (url.origin !== window.location.origin) {
      return null;
    }
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return null;
  }
}

export function getTrustedPostMessageOrigin(targetUrl?: string | null): string {
  const fallbackOrigin = getWindowOrigin();
  if (!targetUrl) {
    return fallbackOrigin;
  }

  try {
    return new URL(targetUrl, fallbackOrigin).origin;
  } catch {
    return fallbackOrigin;
  }
}

export function getSafeExternalUrl(
  value?: string | null,
  options: { allowData?: boolean } = {},
): string | null {
  if (!value) {
    return null;
  }

  const allowedProtocols = options.allowData
    ? IMAGE_ALLOWED_PROTOCOLS
    : DEFAULT_ALLOWED_PROTOCOLS;

  try {
    const url = new URL(value, getWindowOrigin());
    if (!allowedProtocols.has(url.protocol)) {
      return null;
    }
    return url.toString();
  } catch {
    return null;
  }
}
