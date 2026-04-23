"use client";

import { useState } from "react";
import { Network, Sun } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRoleContext } from "@/lib/marketing/RoleContext";
import { ROLE_CONTENT } from "@/lib/marketing/role-content";
import DailyDigestCard from "./DailyDigestCard";
import WeeklyReflectionCard from "./WeeklyReflectionCard";

type Tab = "daily" | "weekly";

/** Client half of the DigestSection. Handles tab state and reads the
 *  active role's digestMock from context. Falls back to researcher's
 *  mock when no role is picked yet, so guests see real content on
 *  first paint. */
export default function DigestSectionClient({ locale }: { locale: "zh" | "en" }) {
  const t = useTranslations("marketing.digest");
  const { role } = useRoleContext();
  const [tab, setTab] = useState<Tab>("daily");

  const digest = (role && ROLE_CONTENT[role].digestMock) || ROLE_CONTENT.researcher.digestMock;
  if (!digest) return null;

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
          <DailyDigestCard data={digest.daily} locale={locale} labels={dailyLabels} />
        ) : (
          <WeeklyReflectionCard data={digest.weekly} locale={locale} labels={weeklyLabels} />
        )}
      </div>
    </>
  );
}
