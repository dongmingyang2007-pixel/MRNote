"use client";

import { useTranslations } from "next-intl";
import { useRoleContext } from "@/lib/marketing/RoleContext";
import { DEFAULT_ROLE, ROLE_CONTENT } from "@/lib/marketing/role-content";
import type { RoleKey } from "@/lib/marketing/role-content";
import { emitLandingEvent } from "@/lib/marketing/analytics";
import RoleChipRow from "./role-selector/RoleChipRow";
import RoleCard from "./role-selector/RoleCard";
import ExclusiveOfferCard from "./role-selector/ExclusiveOfferCard";
import StatHeadline from "./role-selector/StatHeadline";
import TestimonialStrip from "./role-selector/TestimonialStrip";
import InstitutionLogoRow from "./role-selector/InstitutionLogoRow";

interface Props {
  locale: "zh" | "en";
}

export default function ExclusiveSection({ locale }: Props) {
  const t = useTranslations("marketing");
  const { role, setRole } = useRoleContext();

  function handleSelect(next: RoleKey) {
    if (role && role !== next) {
      emitLandingEvent("landing.role.switched", { fromRole: role, toRole: next, locale });
    } else if (!role) {
      emitLandingEvent("landing.role.selected", { role: next, locale });
    }
    setRole(next);
  }

  const effectiveRole: RoleKey = role ?? DEFAULT_ROLE;
  const content = ROLE_CONTENT[effectiveRole];

  return (
    <section
      className="marketing-exclusive"
      aria-label={t("exclusiveSection.eyebrow")}
    >
      <div className="marketing-exclusive__inner">
        <header className="marketing-exclusive__header">
          <span className="marketing-exclusive__eyebrow">
            <span className="marketing-exclusive__eyebrow-dot" aria-hidden="true" />
            {t("exclusiveSection.eyebrow")}
          </span>
          <h2 className="marketing-exclusive__title">
            {t("exclusiveSection.populatedTitle", { role: content.label[locale] })}
          </h2>
          <StatHeadline
            count={content.stat.count}
            prefix={t("exclusiveSection.statLinePrefix")}
            suffix={t("exclusiveSection.statLineSuffix", {
              role: content.label[locale],
              noun: content.domainNoun[locale],
            })}
            asOfTooltip={t("exclusiveSection.statAsOfTooltip", { month: content.stat.asOf })}
          />
        </header>

        <RoleChipRow
          activeRole={effectiveRole}
          onSelect={handleSelect}
          locale={locale}
          groupLabel={t("exclusiveSection.chipsLabel")}
        />

        <div className="marketing-exclusive__cards">
          <RoleCard
            variant="feature"
            label={t("exclusiveSection.cardLabel.demo")}
            title={content.demo.title[locale]}
            description={content.demo.description[locale]}
          />
          <div className="marketing-exclusive__cards-stack">
            <RoleCard
              label={t("exclusiveSection.cardLabel.templatePack")}
              title={content.templatePack.title[locale]}
              description={content.templatePack.items.map((i) => i[locale]).join(" / ")}
              cta={content.templatePack.cta[locale]}
            />
            <ExclusiveOfferCard
              label={t("exclusiveSection.offerLabel")}
              title={content.offer.title[locale]}
              description={content.offer.description[locale]}
              cta={content.offer.cta[locale]}
              href={content.offer.href}
              badge={t("exclusiveSection.offerBadge")}
              onClick={() => emitLandingEvent("landing.offer.clicked", {
                role: effectiveRole,
                offerHref: content.offer.href,
                locale,
              })}
            />
          </div>
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
      </div>
    </section>
  );
}
