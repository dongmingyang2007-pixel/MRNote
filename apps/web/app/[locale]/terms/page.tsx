import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import LegalPage from "@/components/marketing/LegalPage";
import { routing } from "@/i18n/routing";
import "@/styles/marketing.css";

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
  const t = await getTranslations("legal");
  return {
    title: t("terms.meta.title"),
    description: t("terms.meta.description"),
  };
}

export default async function TermsPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const localeKey = locale as (typeof routing.locales)[number];
  if (routing.locales.includes(localeKey)) {
    setRequestLocale(localeKey);
  }
  const t = await getTranslations("legal");

  return (
    <LegalPage title={t("terms.title")} updated={t("terms.updated")}>
      <p>{t("terms.intro")}</p>

      <h2>{t("terms.s1.title")}</h2>
      <p>{t("terms.s1.body")}</p>

      <h2>{t("terms.s2.title")}</h2>
      <p>{t("terms.s2.body")}</p>
      <ul>
        <li>{t("terms.s2.item1")}</li>
        <li>{t("terms.s2.item2")}</li>
        <li>{t("terms.s2.item3")}</li>
        <li>{t("terms.s2.item4")}</li>
      </ul>

      <h2>{t("terms.s3.title")}</h2>
      <p>{t("terms.s3.body")}</p>
      <ul>
        <li>{t("terms.s3.item1")}</li>
        <li>{t("terms.s3.item2")}</li>
        <li>{t("terms.s3.item3")}</li>
        <li>{t("terms.s3.item4")}</li>
        <li>{t("terms.s3.item5")}</li>
      </ul>

      <h2>{t("terms.s4.title")}</h2>
      <p>{t("terms.s4.body")}</p>
      <p>{t("terms.s4.license")}</p>
      <div className="legal-note">
        <strong>{t("terms.s4.noml")}</strong>
      </div>
      <p>{t("terms.s4.responsibility")}</p>

      <h2>{t("terms.s5.title")}</h2>
      <p>{t("terms.s5.body")}</p>
      <ul>
        <li>{t("terms.s5.item1")}</li>
        <li>{t("terms.s5.item2")}</li>
        <li>{t("terms.s5.item3")}</li>
        <li>{t("terms.s5.item4")}</li>
        <li>{t("terms.s5.item5")}</li>
      </ul>

      <h2>{t("terms.s6.title")}</h2>
      <p>{t("terms.s6.body")}</p>
      <ul>
        <li>{t("terms.s6.item1")}</li>
        <li>{t("terms.s6.item2")}</li>
        <li>{t("terms.s6.item3")}</li>
      </ul>

      <h2>{t("terms.s7.title")}</h2>
      <p>{t("terms.s7.by_you")}</p>
      <p>{t("terms.s7.by_us")}</p>
      <p>{t("terms.s7.effect")}</p>

      <h2>{t("terms.s8.title")}</h2>
      <p>{t("terms.s8.asis")}</p>
      <p>{t("terms.s8.limit")}</p>
      <p>{t("terms.s8.noconsequential")}</p>
      <p>{t("terms.s8.law")}</p>
      <p>{t("terms.s8.contact")}</p>
    </LegalPage>
  );
}
