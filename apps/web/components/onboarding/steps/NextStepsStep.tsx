"use client";

import { useTranslations } from "next-intl";

export default function NextStepsStep() {
  const t = useTranslations("onboarding");
  return (
    <>
      <h2 className="onboarding-card__title">{t("nextSteps.title")}</h2>
      <p className="onboarding-card__paragraph">{t("nextSteps.body")}</p>
    </>
  );
}
