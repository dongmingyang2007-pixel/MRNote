"use client";

import { useTranslations } from "next-intl";

export interface PasteNoteStepProps {
  noteText: string;
  onNoteTextChange: (value: string) => void;
}

export default function PasteNoteStep({
  noteText,
  onNoteTextChange,
}: PasteNoteStepProps) {
  const t = useTranslations("onboarding");
  return (
    <>
      <h2 className="onboarding-card__title">{t("pasteNote.title")}</h2>
      <p className="onboarding-card__paragraph">{t("pasteNote.body")}</p>

      <div className="onboarding-field">
        <label className="onboarding-field__label" htmlFor="onb-note">
          {t("pasteNote.label")}
        </label>
        <textarea
          id="onb-note"
          data-testid="onboarding-note-text"
          className="onboarding-textarea"
          value={noteText}
          onChange={(e) => onNoteTextChange(e.target.value)}
          placeholder={t("pasteNote.placeholder")}
        />
        <span className="onboarding-field__hint">{t("pasteNote.hint")}</span>
      </div>
    </>
  );
}
