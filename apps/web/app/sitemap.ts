import type { MetadataRoute } from "next";

const BASE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://mingrun-tech.com";

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  const paths = ["", "pricing", "privacy", "terms", "login", "register"];
  const locales = ["en", "zh"];
  return paths.flatMap((path) =>
    locales.map((locale) => ({
      url: `${BASE_URL}/${locale}${path ? `/${path}` : ""}`,
      lastModified: now,
      changeFrequency: "weekly" as const,
      priority: path === "" ? 1.0 : 0.8,
    }))
  );
}
