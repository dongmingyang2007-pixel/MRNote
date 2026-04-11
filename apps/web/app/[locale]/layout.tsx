import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getMessages, getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";

import { Providers } from "@/components/providers";
import { routing } from "@/i18n/routing";
import "@/styles/globals.css";
import "@/styles/chat-workbench.css";

// Noto Sans SC is loaded via system fonts (PingFang SC / Noto Sans SC)
// in the CSS font-stack rather than next/font to avoid 7MB+ download at build time.

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const localeKey = locale as (typeof routing.locales)[number];

  if (!routing.locales.includes(localeKey)) {
    notFound();
  }

  setRequestLocale(localeKey);
  const t = await getTranslations("common");
  const tc = await getTranslations("console");
  return {
    title: {
      template: `%s - ${t("brand.company")}`,
      default: tc("brand"),
    },
    description: tc("route.assistants.description"),
    openGraph: {
      locale: localeKey === "zh" ? "zh_CN" : "en_US",
    },
    alternates: {
      languages: {
        zh: "/",
        en: "/en",
      },
    },
  };
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const localeKey = locale as (typeof routing.locales)[number];

  if (!routing.locales.includes(localeKey)) {
    notFound();
  }

  setRequestLocale(localeKey);
  const messages = await getMessages();

  return (
    <html lang={localeKey} suppressHydrationWarning>
      <body>
        <NextIntlClientProvider messages={messages}>
          <Providers>{children}</Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
