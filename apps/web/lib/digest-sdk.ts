"use client";

/**
 * Thin client-side SDK for the /api/v1/digest/* endpoints.
 *
 * Backend is being built in parallel (PR 1/x on the server side). These
 * helpers intentionally do not throw on 404 / 401 / 405 — callers want to
 * fall back to mock data or silently skip the drawer when the server hasn't
 * caught up yet, rather than surface an error banner.
 */
import { apiGet, apiPost, isApiRequestError } from "@/lib/api";
import type {
  DailyDigestMock,
  WeeklyReflectionMock,
} from "@/lib/marketing/role-content";

// ---------------------------------------------------------------------------
// Server-side shapes
// ---------------------------------------------------------------------------

/** One row inside a catch / today block. Server already localized the copy
 *  per the caller's locale (Accept-Language cookie), so it's a plain string
 *  here — no { zh, en } wrapper like the mock. */
export interface ServerDigestItem {
  icon: "note" | "sparkles" | "cards" | "book" | "graph" | "file" | "check";
  label: string;
  tag: string;
}

export type ServerDigestBlock =
  | { kind: "catch"; title: string; items: ServerDigestItem[] }
  | { kind: "today"; title: string; items: ServerDigestItem[] }
  | { kind: "insight"; title: string; body: string };

export interface ServerDailyDigest {
  date: string;
  greeting: string;
  blocks: [ServerDigestBlock, ServerDigestBlock, ServerDigestBlock];
}

export interface ServerWeeklyReflection {
  range: string;
  headline: string;
  stats: Array<{ k: string; v: string; trend?: string; trendDir?: "up" | "down" }>;
  moves: string[];
  ask: string;
  options: string[];
  sparkline: number[];
}

// ---------------------------------------------------------------------------
// Render-ready shapes
// ---------------------------------------------------------------------------

/**
 * Both the marketing mocks (with { zh, en } wrappers) and real server
 * responses (flat strings) need to end up in a single render pipeline. We
 * normalize both into `ResolvedDailyDigest` — flat-string shape, locale
 * already resolved — before handing off to `<DailyDigestCard>`.
 */
export interface ResolvedDigestItem {
  icon: ServerDigestItem["icon"];
  label: string;
  tag: string;
}

export type ResolvedDigestBlock =
  | { kind: "catch"; title: string; items: ResolvedDigestItem[] }
  | { kind: "today"; title: string; items: ResolvedDigestItem[] }
  | { kind: "insight"; title: string; body: string };

export interface ResolvedDailyDigest {
  date: string;
  greeting: string;
  blocks: [ResolvedDigestBlock, ResolvedDigestBlock, ResolvedDigestBlock];
}

export interface ResolvedWeeklyReflection {
  range: string;
  headline: string;
  stats: Array<{ k: string; v: string; trend?: string; trendDir?: "up" | "down" }>;
  moves: string[];
  ask: string;
  options: string[];
  sparkline: number[];
}

// ---------------------------------------------------------------------------
// Normalize helpers
// ---------------------------------------------------------------------------

export function normalizeDailyFromMock(
  mock: DailyDigestMock,
  locale: "zh" | "en",
): ResolvedDailyDigest {
  const resolvedBlocks = mock.blocks.map((b): ResolvedDigestBlock => {
    if (b.kind === "insight") {
      return { kind: "insight", title: b.title[locale], body: b.body[locale] };
    }
    const kind = b.kind;
    return {
      kind,
      title: b.title[locale],
      items: b.items.map((it) => ({
        icon: it.icon,
        label: it.label[locale],
        tag: it.tag[locale],
      })),
    };
  }) as ResolvedDailyDigest["blocks"];

  return {
    date: mock.date[locale],
    greeting: mock.greeting[locale],
    blocks: resolvedBlocks,
  };
}

export function normalizeWeeklyFromMock(
  mock: WeeklyReflectionMock,
  locale: "zh" | "en",
): ResolvedWeeklyReflection {
  return {
    range: mock.range[locale],
    headline: mock.headline[locale],
    stats: mock.stats.map((s) => ({
      k: s.k[locale],
      v: s.v,
      trend: s.trend,
      trendDir: s.trendDir,
    })),
    moves: mock.moves.map((m) => m[locale]),
    ask: mock.ask[locale],
    options: mock.options.map((o) => o[locale]),
    sparkline: mock.sparkline,
  };
}

export function normalizeDailyFromServer(server: ServerDailyDigest): ResolvedDailyDigest {
  return {
    date: server.date,
    greeting: server.greeting,
    blocks: server.blocks,
  };
}

export function normalizeWeeklyFromServer(
  server: ServerWeeklyReflection,
): ResolvedWeeklyReflection {
  return server;
}

// ---------------------------------------------------------------------------
// Fetchers
// ---------------------------------------------------------------------------

/** Shared silent-404 swallow: the digest endpoints intentionally return 404
 *  when today/this-week's digest hasn't been generated yet. Callers want a
 *  null return + fallback to mock, not an exception. 401 / 405 (endpoint
 *  not deployed yet) get the same treatment — DigestSection is public-safe
 *  and DigestDrawer self-hides on null. */
function swallowSoft404<T>(err: unknown): T | null {
  if (isApiRequestError(err)) {
    if (err.status === 404 || err.status === 401 || err.status === 405) {
      return null;
    }
  }
  return null; // network / unknown failures also fall back silently
}

export async function fetchDailyDigest(
  dateISO: string,
): Promise<ServerDailyDigest | null> {
  try {
    return await apiGet<ServerDailyDigest>(
      `/api/v1/digest/daily?date=${encodeURIComponent(dateISO)}`,
    );
  } catch (err) {
    return swallowSoft404<ServerDailyDigest>(err);
  }
}

export async function fetchWeeklyReflection(
  weekISO: string,
): Promise<ServerWeeklyReflection | null> {
  try {
    return await apiGet<ServerWeeklyReflection>(
      `/api/v1/digest/weekly?week=${encodeURIComponent(weekISO)}`,
    );
  } catch (err) {
    return swallowSoft404<ServerWeeklyReflection>(err);
  }
}

export async function markDailyRead(dateISO: string): Promise<boolean> {
  try {
    await apiPost<void>("/api/v1/digest/daily/mark-read", { date: dateISO });
    return true;
  } catch {
    return false;
  }
}

export async function saveWeeklyAsPage(
  weekISO: string,
  pickOption?: string,
): Promise<{ page_id: string } | null> {
  try {
    return await apiPost<{ page_id: string }>(
      "/api/v1/digest/weekly/save-as-page",
      pickOption ? { week: weekISO, pickOption } : { week: weekISO },
    );
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Date helpers
// ---------------------------------------------------------------------------

/** Today as YYYY-MM-DD in the visitor's local calendar day. The digest
 *  endpoints treat "today" per user locale-independent date, and we want
 *  the home card to match the user's perception of "today" (not UTC). */
export function todayISO(now: Date = new Date()): string {
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** ISO week string (YYYY-Www) for a given date. Matches Python's
 *  `date.isocalendar()` / `strftime("%G-W%V")`. */
export function isoWeekString(now: Date = new Date()): string {
  // Copy so we can mutate. The algorithm below is the standard ISO 8601
  // week-date computation (Thursday anchor).
  const target = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
  const dayNr = (target.getUTCDay() + 6) % 7; // Mon=0..Sun=6
  target.setUTCDate(target.getUTCDate() - dayNr + 3); // move to Thursday of this ISO week
  const firstThursday = new Date(Date.UTC(target.getUTCFullYear(), 0, 4));
  const firstDayNr = (firstThursday.getUTCDay() + 6) % 7;
  firstThursday.setUTCDate(firstThursday.getUTCDate() - firstDayNr + 3);
  const weekNr =
    1 + Math.round((target.getTime() - firstThursday.getTime()) / (7 * 24 * 3600 * 1000));
  const year = target.getUTCFullYear();
  return `${year}-W${String(weekNr).padStart(2, "0")}`;
}
