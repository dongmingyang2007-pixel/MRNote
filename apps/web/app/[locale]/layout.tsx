import type { Metadata } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import { NextIntlClientProvider } from "next-intl";
import { getMessages, getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";

import { Providers } from "@/components/providers";
import { routing } from "@/i18n/routing";

// Noto Sans SC is loaded via system fonts (PingFang SC / Noto Sans SC)
// in the CSS font-stack rather than next/font to avoid 7MB+ download at build time.
// Plus Jakarta Sans is loaded via next/font for zero FOUT on display/heading text.
const jakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-jakarta",
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
    <html lang={localeKey} className={jakarta.variable} suppressHydrationWarning>
      <body className="font-sans">
        <NextIntlClientProvider messages={messages}>
          <Providers>{children}</Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
