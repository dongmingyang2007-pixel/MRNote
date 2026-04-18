"use client";

import { useTranslations } from "next-intl";

export interface CreateNotebookStepProps {
  clientName: string;
  onClientNameChange: (value: string) => void;
  whatTheyDo: string;
  onWhatTheyDoChange: (value: string) => void;
}

export default function CreateNotebookStep({
  clientName,
  onClientNameChange,
  whatTheyDo,
  onWhatTheyDoChange,
}: CreateNotebookStepProps) {
  const t = useTranslations("onboarding");
  return (
    <>
      <h2 className="onboarding-card__title">
        {t("createNotebook.title")}
      </h2>
      <p className="onboarding-card__paragraph">
        {t("createNotebook.body")}
      </p>

      <div className="onboarding-field">
        <label className="onboarding-field__label" htmlFor="onb-client-name">
          {t("createNotebook.clientName.label")}
        </label>
        <input
          id="onb-client-name"
          data-testid="onboarding-client-name"
          className="onboarding-input"
          type="text"
          value={clientName}
          onChange={(e) => onClientNameChange(e.target.value)}
          placeholder={t("createNotebook.clientName.placeholder")}
          autoComplete="off"
        />
      </div>

      <div className="onboarding-field">
        <label className="onboarding-field__label" htmlFor="onb-what-they-do">
          {t("createNotebook.whatTheyDo.label")}
        </label>
        <input
          id="onb-what-they-do"
          data-testid="onboarding-what-they-do"
          className="onboarding-input"
          type="text"
          value={whatTheyDo}
          onChange={(e) => onWhatTheyDoChange(e.target.value)}
          placeholder={t("createNotebook.whatTheyDo.placeholder")}
          autoComplete="off"
        />
      </div>
    </>
  );
}
