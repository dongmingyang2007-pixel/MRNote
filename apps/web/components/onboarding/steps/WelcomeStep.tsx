"use client";

import { useTranslations } from "next-intl";

export default function WelcomeStep() {
  const t = useTranslations("onboarding");
  return (
    <>
      <h2 className="onboarding-card__title" data-testid="onboarding-welcome-title">
        {t("welcome.title")}
      </h2>
      <p className="onboarding-card__paragraph">{t("welcome.body")}</p>
    </>
  );
}
