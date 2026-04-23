"use client";

import { useEffect, useState } from "react";
import { Network, Sun } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRoleContext } from "@/lib/marketing/RoleContext";
import {
  ROLE_CONTENT,
  type DailyDigestMock,
  type WeeklyReflectionMock,
} from "@/lib/marketing/role-content";
import DailyDigestCard from "./DailyDigestCard";
import WeeklyReflectionCard from "./WeeklyReflectionCard";
import {
  fetchDailyDigest,
  fetchWeeklyReflection,
  isoWeekString,
  todayISO,
  type ServerDailyDigest,
  type ServerWeeklyReflection,
} from "@/lib/digest-sdk";

type Tab = "daily" | "weekly";

/** Both of the existing card components expect the marketing mock shape
 *  (Localized { zh, en } wrappers). The server returns flat strings for the
 *  caller's locale. We fold the server response into the mock shape by
 *  duplicating the single string into both zh/en slots — cheaper than
 *  editing two card components to accept a second shape. */
function serverDailyToMock(server: ServerDailyDigest): DailyDigestMock {
  const wrap = (s: string) => ({ zh: s, en: s });
  const blocks = server.blocks.map((b) => {
    if (b.kind === "insight") {
      return { kind: "insight" as const, title: wrap(b.title), body: wrap(b.body) };
    }
    return {
      kind: b.kind,
      title: wrap(b.title),
      items: b.items.map((it) => ({
        icon: it.icon,
        label: wrap(it.label),
        tag: wrap(it.tag),
      })),
    };
  }) as DailyDigestMock["blocks"];

  return {
    date: wrap(server.date),
    greeting: wrap(server.greeting),
    blocks,
  };
}

function serverWeeklyToMock(server: ServerWeeklyReflection): WeeklyReflectionMock {
  const wrap = (s: string) => ({ zh: s, en: s });
  return {
    range: wrap(server.range),
    headline: wrap(server.headline),
    stats: server.stats.map((s) => ({
      k: wrap(s.k),
      v: s.v,
      trend: s.trend,
      trendDir: s.trendDir,
    })),
    moves: server.moves.map(wrap),
    ask: wrap(server.ask),
    options: server.options.map(wrap),
    sparkline: server.sparkline,
  };
}

/** Client half of the DigestSection. Handles tab state and reads the
 *  active role's digestMock from context. When the visitor is signed in
 *  and the server has a digest for today / this-week, real API data wins;
 *  otherwise we show the persona-driven mock so the page never goes blank. */
export default function DigestSectionClient({ locale }: { locale: "zh" | "en" }) {
  const t = useTranslations("marketing.digest");
  const { role } = useRoleContext();
  const [tab, setTab] = useState<Tab>("daily");

  // Real API overrides (null means "no server data — use mock").
  const [serverDaily, setServerDaily] = useState<DailyDigestMock | null>(null);
  const [serverWeekly, setServerWeekly] = useState<WeeklyReflectionMock | null>(null);

  // Fire-and-forget fetch on mount. Fails silently (guest 401, 404 not-generated,
  // backend not-yet-deployed 404/405) — we simply keep the mock.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const [daily, weekly] = await Promise.all([
        fetchDailyDigest(todayISO()),
        fetchWeeklyReflection(isoWeekString()),
      ]);
      if (cancelled) return;
      if (daily) setServerDaily(serverDailyToMock(daily));
      if (weekly) setServerWeekly(serverWeeklyToMock(weekly));
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const mock = (role && ROLE_CONTENT[role].digestMock) || ROLE_CONTENT.researcher.digestMock;
  if (!mock) return null;

  // Real server data takes precedence; fall back to the persona mock so the
  // homepage never shows an empty rhythm section.
  const daily = serverDaily ?? mock.daily;
  const weekly = serverWeekly ?? mock.weekly;

  const dailyLabels = {
    chromeTitle: t("daily.chromeTitle"),
    dismiss: t("daily.dismiss"),
    startToday: t("daily.startToday"),
    saveInsight: t("daily.saveInsight"),
    arrivesAt: t("daily.arrivesAt"),
  };
  const weeklyLabels = {
    chromeTitle: t("weekly.chromeTitle"),
    saveAsPage: t("weekly.saveAsPage"),
    movesTitle: t("weekly.movesTitle"),
    sparklineLabel: t("weekly.sparklineLabel"),
    weekdayShort: [
      t("weekly.weekdayShort.mon"),
      t("weekly.weekdayShort.tue"),
      t("weekly.weekdayShort.wed"),
      t("weekly.weekdayShort.thu"),
      t("weekly.weekdayShort.fri"),
      t("weekly.weekdayShort.sat"),
      t("weekly.weekdayShort.sun"),
    ] as [string, string, string, string, string, string, string],
  };

  return (
    <>
      <div className="marketing-digest__tabs" role="tablist" aria-label={t("tabsLabel")}>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "daily"}
          className={`marketing-digest__tab ${tab === "daily" ? "is-active" : ""}`}
          onClick={() => setTab("daily")}
        >
          <Sun size={14} aria-hidden="true" />
          <span>{t("tab.daily")}</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "weekly"}
          className={`marketing-digest__tab ${tab === "weekly" ? "is-active" : ""}`}
          onClick={() => setTab("weekly")}
        >
          <Network size={14} aria-hidden="true" />
          <span>{t("tab.weekly")}</span>
        </button>
      </div>

      <div className="marketing-digest__card-wrap" role="tabpanel">
        {tab === "daily" ? (
          <DailyDigestCard data={daily} locale={locale} labels={dailyLabels} />
        ) : (
          <WeeklyReflectionCard data={weekly} locale={locale} labels={weeklyLabels} />
        )}
      </div>
    </>
  );
}
