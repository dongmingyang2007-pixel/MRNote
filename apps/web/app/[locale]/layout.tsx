import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getMessages, getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";

import { Providers } from "@/components/providers";
import { routing } from "@/i18n/routing";

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

const BASE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://mingrun-tech.com";

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
  const tc = await getTranslations("console");
  const tm = await getTranslations("marketing");
  return {
    metadataBase: new URL(BASE_URL),
    title: {
      template: `%s · ${tc("brand")}`,
      default: tc("brand"),
    },
    description: tm("meta.description"),
    openGraph: {
      title: tm("og.title"),
      description: tm("og.description"),
      url: `${BASE_URL}/${localeKey}`,
      siteName: tc("brand"),
      images: [{ url: "/og-image.svg", width: 1200, height: 630, alt: tc("brand") }],
      locale: localeKey === "zh" ? "zh_CN" : "en_US",
      type: "website",
    },
    twitter: {
      card: "summary_large_image",
      title: tm("og.title"),
      description: tm("og.description"),
      images: ["/og-image.svg"],
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
      <body className="font-sans">
        <NextIntlClientProvider messages={messages}>
          <Providers>{children}</Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
