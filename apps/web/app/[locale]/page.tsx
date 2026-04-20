import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { setRequestLocale } from "next-intl/server";

import "@/styles/marketing.css";

import PublicHeader from "@/components/marketing/PublicHeader";
import HeroSection from "@/components/marketing/HeroSection";
import ProblemSection from "@/components/marketing/ProblemSection";
import FeaturesSection from "@/components/marketing/FeaturesSection";
import ScreenshotSection from "@/components/marketing/ScreenshotSection";
import ExclusiveSection from "@/components/marketing/ExclusiveSection";
import PricingSnapshotSection from "@/components/marketing/PricingSnapshotSection";
import CTAFooterSection from "@/components/marketing/CTAFooterSection";
import PublicFooter from "@/components/marketing/PublicFooter";

import { ROLE_KEYS, type RoleKey } from "@/lib/marketing/role-content";
import { ROLE_COOKIE_NAME } from "@/hooks/useRoleSelection";
import { routing } from "@/i18n/routing";

const AUTH_COOKIE_NAMES = [
  "auth_state",
  "mingrun_workspace_id",
  "qihang_workspace_id",
] as const;

function readInitialRole(raw: string | undefined): RoleKey | null {
  if (!raw) return null;
  return (ROLE_KEYS as readonly string[]).includes(raw) ? (raw as RoleKey) : null;
}

export default async function HomePage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const localeKey = locale as (typeof routing.locales)[number];
  if (routing.locales.includes(localeKey)) {
    setRequestLocale(localeKey);
  }

  const cookieStore = await cookies();
  const isLoggedIn = AUTH_COOKIE_NAMES.some((name) => Boolean(cookieStore.get(name)));
  if (isLoggedIn) redirect("/app");

  const initialRole = readInitialRole(cookieStore.get(ROLE_COOKIE_NAME)?.value);
  const sectionLocale: "zh" | "en" = localeKey === "en" ? "en" : "zh";

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg-base)" }}>
      <PublicHeader />
      <main>
        <HeroSection role={initialRole} locale={sectionLocale} />
        <ProblemSection />
        <FeaturesSection />
        <ScreenshotSection />
        <ExclusiveSection initialRole={initialRole} locale={sectionLocale} />
        <PricingSnapshotSection />
        <CTAFooterSection />
      </main>
      <PublicFooter />
    </div>
  );
}
