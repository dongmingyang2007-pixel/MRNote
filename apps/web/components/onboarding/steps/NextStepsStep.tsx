"use client";

import { Check } from "lucide-react";
import { useTranslations } from "next-intl";

export default function NextStepsStep() {
  const t = useTranslations("onboarding");

  const items = [
    t("nextSteps.item1"),
    t("nextSteps.item2"),
    t("nextSteps.item3"),
    t("nextSteps.item4"),
  ] as const;

  return (
    <>
      <h2 className="onboarding-card__title">{t("nextSteps.title")}</h2>
      <p className="onboarding-card__paragraph">{t("nextSteps.body")}</p>

      <ul className="onboarding-checklist">
        {items.map((item, i) => (
          <li key={i} className="onboarding-checklist__item">
            <Check
              size={16}
              strokeWidth={2.5}
              className="onboarding-checklist__icon"
              aria-hidden="true"
            />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </>
  );
}
