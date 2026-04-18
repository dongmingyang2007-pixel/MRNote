"use client";

import { useTranslations } from "next-intl";

export default function MemoryPreviewStep() {
  const t = useTranslations("onboarding");
  return (
    <>
      <h2 className="onboarding-card__title">
        {t("memoryPreview.title")}
      </h2>
      <p className="onboarding-card__paragraph">
        {t("memoryPreview.body")}
      </p>

      <ul
        className="onboarding-memory-list"
        data-testid="onboarding-memory-list"
      >
        <li className="onboarding-memory-item">
          {t("memoryPreview.example1")}
        </li>
        <li className="onboarding-memory-item">
          {t("memoryPreview.example2")}
        </li>
        <li className="onboarding-memory-item">
          {t("memoryPreview.example3")}
        </li>
      </ul>

      <p className="onboarding-note">{t("memoryPreview.note")}</p>
    </>
  );
}
