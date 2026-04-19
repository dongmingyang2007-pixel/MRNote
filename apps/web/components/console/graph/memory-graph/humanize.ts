const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export function humanizeRelativeTime(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const ts = new Date(iso).getTime();
  if (!Number.isFinite(ts)) return null;
  const deltaMs = Math.max(0, Date.now() - ts);
  if (deltaMs < HOUR) return `${Math.floor(deltaMs / MINUTE)}m`;
  if (deltaMs < DAY) return `${Math.floor(deltaMs / HOUR)}h`;
  return `${Math.floor(deltaMs / DAY)}d`;
}
