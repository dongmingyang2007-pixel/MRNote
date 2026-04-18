"use client";

import { Brain, Check } from "lucide-react";
import { useTranslations } from "next-intl";

export default function MemoryPreviewStep() {
  const t = useTranslations("onboarding");

  const examples = [
    t("memoryPreview.example1"),
    t("memoryPreview.example2"),
    t("memoryPreview.example3"),
  ] as const;

  return (
    <>
      <h2 className="onboarding-card__title">
        {t("memoryPreview.title")}
      </h2>
      <p className="onboarding-card__paragraph">
        {t("memoryPreview.body")}
      </p>

      <p className="onboarding-memory-caption">
        {t("memoryPreview.caption")}
      </p>

      <ul
        className="onboarding-memory-list"
        data-testid="onboarding-memory-list"
      >
        {examples.map((text, i) => (
          <li key={i} className="onboarding-memory-card">
            <Brain
              size={16}
              strokeWidth={1.75}
              className="onboarding-memory-card__icon"
              aria-hidden="true"
            />
            <span className="onboarding-memory-card__text">{text}</span>
            <Check
              size={14}
              strokeWidth={2.5}
              className="onboarding-memory-card__check"
              aria-hidden="true"
            />
          </li>
        ))}
      </ul>

      <p className="onboarding-memory-subcaption">
        {t("memoryPreview.subcaption")}
      </p>
    </>
  );
}
