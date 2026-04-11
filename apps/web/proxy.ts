import { NextRequest, NextResponse } from "next/server";
import {
  DEFAULT_LOCAL_API_PORT,
  LOOPBACK_HOSTS,
  isLoopbackHost,
  isLocalBindHost,
} from "@/lib/network-hosts";
import {
  DISCOVER_ENABLED,
  resolveDiscoverRedirectTarget,
} from "@/lib/feature-flags";

const AUTH_STATE_COOKIE = "auth_state";
const AUTH_STATE_COOKIE_VALUE = "1";
const CSP_LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1"]);

function normalizeOrigin(value?: string): string | null {
  if (!value) {
    return null;
  }
  try {
    const url = new URL(value);
    return `${url.protocol}//${url.host}`;
  } catch {
    return null;
  }
}

function expandLoopbackOrigins(
  origin: string | null,
  loopbackHosts: Iterable<string> = LOOPBACK_HOSTS,
): string[] {
  if (!origin) {
    return [];
  }

  const origins = [origin];
  try {
    const url = new URL(origin);
    if (isLoopbackHost(url.hostname) || isLocalBindHost(url.hostname)) {
      for (const loopbackHost of loopbackHosts) {
        if (loopbackHost === url.hostname) {
          continue;
        }
        url.hostname = loopbackHost;
        origins.push(`${url.protocol}//${url.host}`);
      }
    }
  } catch {
    return origins;
  }

  return Array.from(new Set(origins));
}

function expandConnectOrigins(origins: string[]): string[] {
  const expanded = new Set(origins);
  for (const origin of origins) {
    try {
      const url = new URL(origin);
      if (url.protocol === "http:") {
        expanded.add(`ws://${url.host}`);
      } else if (url.protocol === "https:") {
        expanded.add(`wss://${url.host}`);
      }
    } catch {
      continue;
    }
  }
  return Array.from(expanded);
}

function defaultLocalApiOrigins(request: NextRequest): string[] {
  const { protocol, hostname } = request.nextUrl;
  if (!isLoopbackHost(hostname)) {
    return [];
  }
  return expandLoopbackOrigins(
    `${protocol}//${hostname}:${DEFAULT_LOCAL_API_PORT}`,
    CSP_LOOPBACK_HOSTS,
  );
}

function isProtectedConsolePath(pathname: string): boolean {
  return pathname === "/app" || pathname.startsWith("/app/");
}

function isDiscoverPath(pathname: string): boolean {
  return pathname === "/app/discover" || pathname.startsWith("/app/discover/");
}

function isEnglishPath(pathname: string): boolean {
  return pathname === "/en" || pathname.startsWith("/en/");
}

function getLocalePrefix(request: NextRequest): string {
  const rawPathname = new URL(request.url).pathname;
  return isEnglishPath(rawPathname) ? "/en" : "";
}

function buildCsp(
  request: NextRequest,
  allowSameOriginFrame: boolean,
  scriptSrc: string,
): string {
  const configuredApiOrigins = expandLoopbackOrigins(
    normalizeOrigin(process.env.NEXT_PUBLIC_API_BASE_URL),
    CSP_LOOPBACK_HOSTS,
  );
  const apiOrigins =
    configuredApiOrigins.length > 0
      ? configuredApiOrigins
      : defaultLocalApiOrigins(request);
  const assetOrigins = expandLoopbackOrigins(
    normalizeOrigin(process.env.NEXT_PUBLIC_ASSET_ORIGIN),
    CSP_LOOPBACK_HOSTS,
  );
  const connectOrigins = expandConnectOrigins([...apiOrigins, ...assetOrigins]);
  const connectSrc = ["'self'", "blob:", ...connectOrigins].join(" ");
  const assetSrc = [
    "'self'",
    "data:",
    "blob:",
    ...apiOrigins,
    ...assetOrigins,
  ].join(" ");
  const frameAncestors = allowSameOriginFrame ? "'self'" : "'none'";

  return [
    "default-src 'self'",
    `script-src ${scriptSrc}`,
    "style-src 'self' 'unsafe-inline'",
    `img-src ${assetSrc}`,
    `media-src ${assetSrc}`,
    `connect-src ${connectSrc}`,
    "font-src 'self' data:",
    "frame-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    `frame-ancestors ${frameAncestors}`,
  ].join("; ");
}

export function proxy(request: NextRequest) {
  const rawPathname = new URL(request.url).pathname;
  const allowSameOriginFrame = false;
  const hasAccessToken = Boolean(request.cookies.get("access_token")?.value);
  const hasAuthState =
    request.cookies.get(AUTH_STATE_COOKIE)?.value === AUTH_STATE_COOKIE_VALUE;

  // Strip locale prefix so /en/app/* is also handled correctly
  const strippedPath = rawPathname.replace(/^\/(en|zh)(?=\/|$)/, "") || "/";
  const localePrefix = getLocalePrefix(request);

  if (!DISCOVER_ENABLED && isDiscoverPath(strippedPath)) {
    const from = request.nextUrl.searchParams.get("from");
    const redirectTarget = resolveDiscoverRedirectTarget(
      localePrefix === "/en" ? "en" : "zh",
      from,
    );
    return NextResponse.redirect(new URL(redirectTarget, request.url), 307);
  }

  // Auth check
  if (isProtectedConsolePath(strippedPath) && !hasAccessToken) {
    const loginUrl = new URL(`${localePrefix}/login`, request.url);
    loginUrl.searchParams.set(
      "next",
      `${rawPathname}${request.nextUrl.search}`,
    );
    const redirect = NextResponse.redirect(loginUrl);
    if (hasAuthState) {
      redirect.cookies.delete(AUTH_STATE_COOKIE);
    }
    return redirect;
  }

  const isLocalHost = isLoopbackHost(request.nextUrl.hostname);
  const isLocalStack = process.env.QIHANG_LOCAL_STACK === "true";
  const useNonceCsp =
    process.env.NODE_ENV === "production" && !isLocalHost && !isLocalStack;
  let nonce: string | null = null;
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-app-locale", localePrefix === "/en" ? "en" : "zh");
  const response = NextResponse.next({
    request: {
      headers: requestHeaders,
    },
  });

  // Generate nonce for CSP (production only)
  if (useNonceCsp) {
    nonce = btoa(crypto.randomUUID());
  }

  // Security headers — applied to every response (including intl redirects)
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  response.headers.set(
    "X-Frame-Options",
    allowSameOriginFrame ? "SAMEORIGIN" : "DENY",
  );
  response.headers.set(
    "Permissions-Policy",
    "camera=(self), microphone=(self), geolocation=(), browsing-topics=()",
  );

  if (process.env.NODE_ENV === "production") {
    const scriptSrc = nonce
      ? `'self' 'nonce-${nonce}' 'strict-dynamic'`
      : "'self' 'unsafe-inline'";
    response.headers.set(
      "Content-Security-Policy",
      buildCsp(request, allowSameOriginFrame, scriptSrc),
    );
  }

  if (hasAccessToken && !hasAuthState) {
    response.cookies.set(AUTH_STATE_COOKIE, AUTH_STATE_COOKIE_VALUE, {
      path: "/",
      sameSite: "lax",
    });
  } else if (!hasAccessToken && hasAuthState) {
    response.cookies.delete(AUTH_STATE_COOKIE);
  }

  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
