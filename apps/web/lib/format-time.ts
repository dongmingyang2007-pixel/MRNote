// eslint-disable-next-line @typescript-eslint/no-explicit-any
type TranslateFn = (key: any, values?: any) => string;

export function formatRelativeTime(dateStr: string, t: TranslateFn): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return t("time.justNow");
  if (diffMins < 60) return t("time.minutesAgo", { n: diffMins });
  if (diffHours < 24) return t("time.hoursAgo", { n: diffHours });
  return t("time.daysAgo", { n: diffDays });
}
