export const DISCOVER_ENABLED = false;

export function resolveDiscoverRedirectTarget(
  locale: string,
  from?: string | null,
): string {
  const fallback = locale === "en" ? "/en/app" : "/app";

  if (!from || !from.startsWith("/")) {
    return fallback;
  }

  if (from.startsWith("/en/") || from.startsWith("/zh/")) {
    return from;
  }

  return locale === "en" ? `/en${from}` : from;
}
