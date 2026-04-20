"use client";

import { useTranslations } from "next-intl";
import { useRoleContext } from "@/lib/marketing/RoleContext";
import { ROLE_CONTENT } from "@/lib/marketing/role-content";
import type { RoleKey } from "@/lib/marketing/role-content";
import { emitLandingEvent } from "@/lib/marketing/analytics";
import RoleChipRow from "./role-selector/RoleChipRow";
import RoleCard from "./role-selector/RoleCard";
import ExclusiveOfferCard from "./role-selector/ExclusiveOfferCard";
import StatCounter from "./role-selector/StatCounter";
import TestimonialStrip from "./role-selector/TestimonialStrip";
import InstitutionLogoRow from "./role-selector/InstitutionLogoRow";

interface Props {
  locale: "zh" | "en";
}

export default function ExclusiveSection({ locale }: Props) {
  const t = useTranslations("marketing");
  const { role, setRole, clearRole } = useRoleContext();

  function handleSelect(next: RoleKey) {
    if (role && role !== next) {
      emitLandingEvent("landing.role.switched", { fromRole: role, toRole: next, locale });
    } else if (!role) {
      emitLandingEvent("landing.role.selected", { role: next, locale });
    }
    setRole(next);
  }

  function handleClear() {
    if (role) emitLandingEvent("landing.role.cleared", { fromRole: role, locale });
    clearRole();
  }

  const content = role ? ROLE_CONTENT[role] : null;

  return (
    <section
      className="marketing-exclusive"
      aria-label={t("exclusiveSection.eyebrow")}
    >
      <div className="marketing-exclusive__inner">
        <span className="marketing-exclusive__eyebrow">{t("exclusiveSection.eyebrow")}</span>

        {content ? (
          <>
            <h2 className="marketing-exclusive__title">
              {t("exclusiveSection.populatedTitle", { role: content.label[locale] })}
            </h2>
            <p className="marketing-exclusive__stat-line">
              {t("exclusiveSection.statLinePrefix")}
              <strong title={t("exclusiveSection.statAsOfTooltip", { month: content.stat.asOf })}>
                <StatCounter target={content.stat.count} />
              </strong>
              {t("exclusiveSection.statLineSuffix", {
                role: content.label[locale],
                noun: content.domainNoun[locale],
              })}
              <button
                type="button"
                className="marketing-exclusive__switch"
                onClick={handleClear}
              >
                {t("exclusiveSection.switch")}
              </button>
            </p>

            <RoleChipRow activeRole={role} onSelect={handleSelect} locale={locale} groupLabel={t("exclusiveSection.chipsLabel")} />

            <div className="marketing-exclusive__cards">
              <RoleCard
                label={t("exclusiveSection.cardLabel.demo")}
                title={content.demo.title[locale]}
                description={content.demo.description[locale]}
              />
              <RoleCard
                label={t("exclusiveSection.cardLabel.templatePack")}
                title={content.templatePack.title[locale]}
                description={content.templatePack.items.map((i) => i[locale]).join(" / ")}
                cta={content.templatePack.cta[locale]}
              />
              <ExclusiveOfferCard
                title={content.offer.title[locale]}
                description={content.offer.description[locale]}
                cta={content.offer.cta[locale]}
                href={content.offer.href}
                badge={t("exclusiveSection.offerBadge")}
                onClick={() => emitLandingEvent("landing.offer.clicked", {
                  role: role as string,
                  offerHref: content.offer.href,
                  locale,
                })}
              />
            </div>

            <TestimonialStrip
              quote={content.testimonial.quote[locale]}
              name={content.testimonial.name}
              title={content.testimonial.title[locale]}
              avatarInitial={content.testimonial.avatarInitial}
            />

            <InstitutionLogoRow
              heading={t("exclusiveSection.logosHeading")}
              names={content.institutions}
            />
          </>
        ) : (
          <>
            <h2 className="marketing-exclusive__title">
              {t("exclusiveSection.emptyTitle")}
            </h2>
            <p className="marketing-exclusive__hint">{t("exclusiveSection.emptyHint")}</p>
            <RoleChipRow activeRole={null} onSelect={handleSelect} locale={locale} groupLabel={t("exclusiveSection.chipsLabel")} />
            <div className="marketing-exclusive__cards">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="marketing-exclusive__card marketing-exclusive__card--placeholder"
                  aria-hidden="true"
                >
                  {t("exclusiveSection.placeholderCard")}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
