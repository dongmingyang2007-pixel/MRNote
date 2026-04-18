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
    title: t("privacy.meta.title"),
    description: t("privacy.meta.description"),
  };
}

export default async function PrivacyPage({
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
    <LegalPage title={t("privacy.title")} updated={t("privacy.updated")}>
      <p>{t("privacy.intro")}</p>

      <h2>{t("privacy.s1.title")}</h2>
      <p style={{ whiteSpace: "pre-line" }}>{t("privacy.s1.body")}</p>

      <h2>{t("privacy.s2.title")}</h2>
      <p>{t("privacy.s2.body")}</p>
      <ul>
        <li>{t("privacy.s2.item1")}</li>
        <li>{t("privacy.s2.item2")}</li>
        <li>{t("privacy.s2.item3")}</li>
        <li>{t("privacy.s2.item4")}</li>
      </ul>

      <h2>{t("privacy.s3.title")}</h2>
      <p>{t("privacy.s3.body")}</p>
      <ul>
        <li>{t("privacy.s3.item1")}</li>
        <li>{t("privacy.s3.item2")}</li>
        <li>{t("privacy.s3.item3")}</li>
        <li>{t("privacy.s3.item4")}</li>
      </ul>
      <div className="legal-note">
        <strong>{t("privacy.s3.noml")}</strong>
      </div>

      <h2>{t("privacy.s4.title")}</h2>
      <p>{t("privacy.s4.body")}</p>
      <ul>
        <li>{t("privacy.s4.item1")}</li>
        <li>{t("privacy.s4.item2")}</li>
        <li>{t("privacy.s4.item3")}</li>
      </ul>
      <p>{t("privacy.s4.noads")}</p>

      <h2>{t("privacy.s5.title")}</h2>
      <p>{t("privacy.s5.body")}</p>
      <ul>
        <li>{t("privacy.s5.item1")}</li>
        <li>{t("privacy.s5.item2")}</li>
        <li>{t("privacy.s5.item3")}</li>
      </ul>

      <h2>{t("privacy.s6.title")}</h2>
      <p>{t("privacy.s6.body")}</p>
      <ul>
        <li>{t("privacy.s6.item1")}</li>
        <li>{t("privacy.s6.item2")}</li>
        <li>{t("privacy.s6.item3")}</li>
        <li>{t("privacy.s6.item4")}</li>
      </ul>
      <p>{t("privacy.s6.contact")}</p>

      <h2>{t("privacy.s7.title")}</h2>
      <p>{t("privacy.s7.body")}</p>
      <ul>
        <li>{t("privacy.s7.item1")}</li>
        <li>{t("privacy.s7.item2")}</li>
      </ul>
      <p>{t("privacy.s7.notrack")}</p>

      <h2>{t("privacy.s8.title")}</h2>
      <p>{t("privacy.s8.body")}</p>
      <p>{t("privacy.s8.contact")}</p>
    </LegalPage>
  );
}
