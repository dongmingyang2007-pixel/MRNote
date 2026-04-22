import { cookies } from "next/headers";
import { setRequestLocale } from "next-intl/server";

import "@/styles/marketing.css";

import PublicHeader from "@/components/marketing/PublicHeader";
import HeroSection from "@/components/marketing/HeroSection";
import { RoleProvider } from "@/lib/marketing/RoleContext";
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
  const initialRole = readInitialRole(cookieStore.get(ROLE_COOKIE_NAME)?.value);
  const sectionLocale: "zh" | "en" = localeKey === "en" ? "en" : "zh";

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg-base)" }}>
      <PublicHeader />
      <main>
        <RoleProvider initialRole={initialRole} locale={sectionLocale}>
          <HeroSection locale={sectionLocale} />
          <ProblemSection />
          <FeaturesSection />
          <ScreenshotSection />
          <ExclusiveSection locale={sectionLocale} />
          <PricingSnapshotSection />
        </RoleProvider>
        <CTAFooterSection />
      </main>
      <PublicFooter />
    </div>
  );
}
