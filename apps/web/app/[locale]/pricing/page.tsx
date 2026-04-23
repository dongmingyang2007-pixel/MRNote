import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import "@/styles/marketing.css";

import PublicHeader from "@/components/marketing/PublicHeader";
import PublicFooter from "@/components/marketing/PublicFooter";
import PricingHero from "@/components/marketing/PricingHero";
import PricingTable from "@/components/marketing/PricingTable";
import FeatureComparisonTable from "@/components/marketing/FeatureComparisonTable";
import FAQSection from "@/components/marketing/FAQSection";

import { routing } from "@/i18n/routing";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const localeKey = locale as (typeof routing.locales)[number];
  if (routing.locales.includes(localeKey)) {
    setRequestLocale(localeKey);
  }
  const t = await getTranslations("marketing");
  return {
    title: t("pricingPage.meta.title"),
    description: t("pricingPage.hero.sub"),
  };
}

export default async function PricingPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const localeKey = locale as (typeof routing.locales)[number];
  if (routing.locales.includes(localeKey)) {
    setRequestLocale(localeKey);
  }

  return (
    // `.marketing-theme` scopes the `--mkt-*` tokens onto this tree so
    // PublicHeader / PublicFooter / FeatureComparisonTable / FAQSection
    // resolve the same teal + orange palette as the homepage.
    <div
      className="marketing-theme"
      style={{ minHeight: "100vh", background: "#F7FEFC" }}
    >
      <PublicHeader />
      <main>
        <PricingHero />
        <PricingTable />
        <FeatureComparisonTable />
        <FAQSection />
      </main>
      <PublicFooter />
    </div>
  );
}
