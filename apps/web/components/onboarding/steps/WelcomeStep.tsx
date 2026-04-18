"use client";

import { Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

export default function WelcomeStep() {
  const t = useTranslations("onboarding");
  return (
    <div className="onboarding-welcome">
      {/* Brand icon block */}
      <div className="onboarding-welcome__icon" aria-hidden="true">
        <Sparkles size={28} strokeWidth={1.75} />
      </div>

      <h2
        className="onboarding-welcome__title"
        data-testid="onboarding-welcome-title"
      >
        {t("welcome.title")}
      </h2>

      <p className="onboarding-welcome__body">{t("welcome.body")}</p>

      {/* Time-expectation pill */}
      <span className="onboarding-welcome__pill">
        <Sparkles size={12} strokeWidth={2} aria-hidden="true" />
        {t("welcome.timePill")}
      </span>
    </div>
  );
}
