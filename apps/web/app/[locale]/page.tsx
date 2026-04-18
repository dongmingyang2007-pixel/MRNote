import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { setRequestLocale } from "next-intl/server";

import "@/styles/marketing.css";

import PublicHeader from "@/components/marketing/PublicHeader";
import HeroSection from "@/components/marketing/HeroSection";
import ProblemSection from "@/components/marketing/ProblemSection";
import FeaturesSection from "@/components/marketing/FeaturesSection";
import ScreenshotSection from "@/components/marketing/ScreenshotSection";
import PricingSnapshotSection from "@/components/marketing/PricingSnapshotSection";
import CTAFooterSection from "@/components/marketing/CTAFooterSection";
import PublicFooter from "@/components/marketing/PublicFooter";

import { routing } from "@/i18n/routing";

// Auth cookies: set client-side in lib/auth-state.ts and lib/api.ts.
// - `auth_state` is written on login (value "1") and cleared on logout.
// - `mingrun_workspace_id` is written alongside; legacy variant:
//   `qihang_workspace_id`. If any is present we bounce to /app so the
//   workspace loader can finish resolving the session.
const AUTH_COOKIE_NAMES = [
  "auth_state",
  "mingrun_workspace_id",
  "qihang_workspace_id",
] as const;

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

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg-base)" }}>
      <PublicHeader />
      <main>
        <HeroSection />
        <ProblemSection />
        <FeaturesSection />
        <ScreenshotSection />
        <PricingSnapshotSection />
        <CTAFooterSection />
      </main>
      <PublicFooter />
    </div>
  );
}
