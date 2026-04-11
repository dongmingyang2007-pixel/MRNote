"use client";

import { useTranslations } from "next-intl";

const COLOR_OPTIONS = [
  { name: "accent", value: "var(--accent)" },
  { name: "blue", value: "#3b82f6" },
  { name: "green", value: "#22c55e" },
  { name: "purple", value: "#8b5cf6" },
  { name: "pink", value: "#ec4899" },
  { name: "orange", value: "#f97316" },
];

interface StepIdentityProps {
  name: string;
  color: string;
  greeting: string;
  onNameChange: (name: string) => void;
  onColorChange: (color: string) => void;
  onGreetingChange: (greeting: string) => void;
}

export function StepIdentity({
  name,
  color,
  greeting,
  onNameChange,
  onColorChange,
  onGreetingChange,
}: StepIdentityProps) {
  const t = useTranslations("console-assistants");

  const activeColor = COLOR_OPTIONS.find((c) => c.name === color) ?? COLOR_OPTIONS[0];

  return (
    <div className="wizard-step-identity">
      <h2 className="wizard-step-title">{t("wizard.identity.title")}</h2>
      <p className="wizard-step-desc">{t("wizard.identity.subtitle")}</p>

      <div className="wizard-identity-layout">
        {/* Left: avatar preview + color picker */}
        <div className="wizard-identity-left">
          <div
            className="wizard-identity-avatar"
            style={{ background: activeColor.value }}
          >
            <svg
              width="48"
              height="48"
              viewBox="0 0 24 24"
              fill="none"
              stroke="white"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="3" y="11" width="18" height="10" rx="2" />
              <circle cx="8.5" cy="15.5" r="1.5" />
              <circle cx="15.5" cy="15.5" r="1.5" />
              <path d="M8 11V7a4 4 0 0 1 8 0v4" />
            </svg>
          </div>

          <div className="wizard-color-picker">
            {COLOR_OPTIONS.map((c) => (
              <button
                key={c.name}
                type="button"
                className={`wizard-color-swatch ${color === c.name ? "wizard-color-swatch--selected" : ""}`}
                style={{ background: c.value }}
                onClick={() => onColorChange(c.name)}
                aria-label={c.name}
              />
            ))}
          </div>
        </div>

        {/* Right: name + greeting inputs */}
        <div className="wizard-identity-right">
          <div className="wizard-field">
            <label className="wizard-label" htmlFor="identity-name">
              {t("wizard.identity.nameLabel")}
            </label>
            <input
              id="identity-name"
              type="text"
              className="wizard-input"
              value={name}
              onChange={(e) => onNameChange(e.target.value)}
              placeholder={t("wizard.identity.namePlaceholder")}
              maxLength={50}
            />
          </div>

          <div className="wizard-field">
            <label className="wizard-label" htmlFor="identity-greeting">
              {t("wizard.identity.greetingLabel")}
            </label>
            <textarea
              id="identity-greeting"
              className="wizard-textarea"
              rows={3}
              value={greeting}
              onChange={(e) => onGreetingChange(e.target.value)}
              placeholder={t("wizard.identity.greetingPlaceholder")}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
