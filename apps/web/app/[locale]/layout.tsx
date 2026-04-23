import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getMessages, getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";
import { Plus_Jakarta_Sans, JetBrains_Mono } from "next/font/google";

import { Providers } from "@/components/providers";
import { routing } from "@/i18n/routing";

// next/font/google self-hosts the font files at build-time and exposes
// a CSS variable per family. We intentionally DO NOT load Noto Sans SC
// here — Google Fonts only offers it as a dynamic subset, which is not
// supported by `next/font/google` today. Chinese glyph coverage stays
// on the `@import` in globals.css until that changes. When the Chinese
// subset ships, add it back and drop the Noto import from globals.css.
const plusJakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700", "800"],
  variable: "--font-plus-jakarta",
  display: "swap",
});

const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-jetbrains",
  display: "swap",
});

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
    <html
      lang={localeKey}
      className={`${plusJakarta.variable} ${jetbrains.variable}`}
      suppressHydrationWarning
    >
      <body className="font-sans">
        <NextIntlClientProvider messages={messages}>
          <Providers>{children}</Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
