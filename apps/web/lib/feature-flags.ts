export const DISCOVER_ENABLED = false;

export function resolveDiscoverRedirectTarget(
  locale: string,
  from?: string | null,
): string {
  const fallback = locale === "en" ? "/en/app" : "/app";

  if (
    !from ||
    !from.startsWith("/") ||
    from.startsWith("//") ||
    from.includes("\\")
  ) {
    return fallback;
  }
  try {
    const parsed = new URL(from, "https://mrai.local");
    if (
      parsed.origin !== "https://mrai.local" ||
      !parsed.pathname.replace(/^\/(en|zh)(?=\/|$)/, "").startsWith("/app")
    ) {
      return fallback;
    }
    from = `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return fallback;
  }

  if (from.startsWith("/en/") || from.startsWith("/zh/")) {
    return from;
  }

  return locale === "en" ? `/en${from}` : from;
}
