"use client";

import { useTranslations } from "next-intl";
import { useCallback, useMemo } from "react";

type TemplateId = "warm" | "efficient" | "tutor" | "creative" | "analyst" | "humor";

const TEMPLATE_IDS: readonly TemplateId[] = [
  "warm", "efficient", "tutor", "creative", "analyst", "humor",
] as const;

type TagId =
  | "professional"
  | "friendly"
  | "humor"
  | "rigorous"
  | "creative"
  | "patient";

const TAG_IDS: readonly TagId[] = [
  "professional", "friendly", "humor", "rigorous", "creative", "patient",
] as const;

interface PersonalityData {
  description: string;
  tags: string[];
}

interface StepPersonalityProps {
  personality: PersonalityData;
  onPersonalityChange: (data: PersonalityData) => void;
}

export function StepPersonality({ personality, onPersonalityChange }: StepPersonalityProps) {
  const t = useTranslations("console-assistants");

  const templates = useMemo(
    () =>
      TEMPLATE_IDS.map((id) => ({
        id,
        label: t(`wizard.personality.preset.${id}.label`),
        hint: t(`wizard.personality.preset.${id}.hint`),
        prompt: t(`wizard.personality.preset.${id}.prompt`),
      })),
    [t],
  );

  const tags = useMemo(
    () =>
      TAG_IDS.map((id) => ({
        id,
        label: t(`wizard.personality.tag.${id}`),
      })),
    [t],
  );

  const selectTemplate = useCallback(
    (prompt: string) => {
      onPersonalityChange({
        ...personality,
        description: prompt,
      });
    },
    [personality, onPersonalityChange],
  );

  const toggleTag = useCallback(
    (tagLabel: string) => {
      const next = personality.tags.includes(tagLabel)
        ? personality.tags.filter((t) => t !== tagLabel)
        : [...personality.tags, tagLabel];
      onPersonalityChange({ ...personality, tags: next });
    },
    [personality, onPersonalityChange],
  );

  return (
    <div className="wizard-step-personality">
      <h2 className="wizard-step-title">{t("wizard.personality.title")}</h2>
      <p className="wizard-step-desc">{t("wizard.personality.subtitle")}</p>

      <div className="wizard-personality-grid">
        {templates.map((tmpl) => (
          <button
            key={tmpl.id}
            type="button"
            className={`wizard-personality-card ${personality.description === tmpl.prompt && tmpl.prompt ? "wizard-personality-card--selected" : ""}`}
            onClick={() => selectTemplate(tmpl.prompt)}
          >
            <span className="wizard-personality-label">{tmpl.label}</span>
            <span className="wizard-personality-hint">{tmpl.hint}</span>
          </button>
        ))}
      </div>

      <div className="wizard-personality-prompt">
        <label className="wizard-label" htmlFor="personality-textarea">
          {t("wizard.promptLabel")}
        </label>
        <textarea
          id="personality-textarea"
          className="wizard-textarea"
          rows={4}
          value={personality.description}
          onChange={(e) =>
            onPersonalityChange({ ...personality, description: e.target.value })
          }
          placeholder={t("wizard.promptPlaceholder")}
        />
      </div>

      <div className="wizard-personality-tags">
        <span className="wizard-label">{t("wizard.tagsLabel")}</span>
        <div className="wizard-tag-chips">
          {tags.map((tag) => (
            <button
              key={tag.id}
              type="button"
              className={`wizard-tag-chip ${personality.tags.includes(tag.label) ? "wizard-tag-chip--active" : ""}`}
              onClick={() => toggleTag(tag.label)}
            >
              {tag.label}
            </button>
          ))}
        </div>
      </div>

    </div>
  );
}
