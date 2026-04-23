"use client";

import { ArrowRight, PlayCircle } from "lucide-react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { useRoleContext } from "@/lib/marketing/RoleContext";
import { ROLE_CONTENT } from "@/lib/marketing/role-content";

/**
 * Hero copy + CTA that swaps by active role (persona). Falls back to the
 * static i18n strings when no role is selected yet, so SSR/first paint
 * stays stable. Title is split into prefix + <em> + middle + <mark> +
 * optional suffix so interleaved highlights stay editable from
 * role-content.ts without raw HTML in JSON.
 */
export default function HeroPersonaCopy({ locale }: { locale: "zh" | "en" }) {
  const t = useTranslations("marketing");
  const { role } = useRoleContext();
  const hero = role ? ROLE_CONTENT[role].hero : undefined;

  if (!hero) {
    return (
      <>
        <span className="marketing-eyebrow mb-4">{t("hero.kicker")}</span>
        <h1 className="marketing-h1 font-display tracking-tight text-4xl md:text-6xl lg:text-7xl mb-6 md:mb-8">
          {t("hero.title")}
        </h1>
        <p
          className="marketing-lead text-lg md:text-xl leading-relaxed mb-8 md:mb-10"
          style={{ maxWidth: 580 }}
        >
          {t("hero.sub")}
        </p>
        <div className="marketing-hero__cta-row">
          <Link
            href="/register"
            className="marketing-btn marketing-btn--primary marketing-btn--lg"
          >
            {t("hero.cta.primary")}
            <ArrowRight size={16} />
          </Link>
          <Link
            href="/#features"
            className="marketing-btn marketing-btn--secondary marketing-btn--lg"
          >
            <PlayCircle size={16} />
            {t("hero.cta.secondary")}
          </Link>
        </div>
      </>
    );
  }

  const {
    kicker,
    title: { prefix, emphasis, middle, mark, suffix },
    sub,
    primaryCta,
    secondaryCta,
    footBadges,
  } = hero;

  return (
    <>
      <span className="marketing-eyebrow mb-4">{kicker[locale]}</span>
      <h1 className="marketing-h1 font-display tracking-tight text-4xl md:text-6xl lg:text-7xl mb-6 md:mb-8">
        {prefix[locale]}
        <em className="marketing-hero__title-em">{emphasis[locale]}</em>
        {middle[locale]}
        <mark className="marketing-hero__title-mark">{mark[locale]}</mark>
        {suffix?.[locale] ?? ""}
      </h1>
      <p
        className="marketing-lead text-lg md:text-xl leading-relaxed mb-8 md:mb-10"
        style={{ maxWidth: 580 }}
      >
        {sub[locale]}
      </p>
      <div className="marketing-hero__cta-row">
        <Link
          href="/register"
          className="marketing-btn marketing-btn--primary marketing-btn--lg"
        >
          {primaryCta[locale]}
          <ArrowRight size={16} />
        </Link>
        <Link
          href="/#features"
          className="marketing-btn marketing-btn--secondary marketing-btn--lg"
        >
          <PlayCircle size={16} />
          {secondaryCta[locale]}
        </Link>
      </div>
      <ul className="marketing-hero__foot-badges" aria-label={t("hero.footBadgesLabel")}>
        {footBadges.map((badge) => (
          <li key={badge[locale]}>{badge[locale]}</li>
        ))}
      </ul>
    </>
  );
}
