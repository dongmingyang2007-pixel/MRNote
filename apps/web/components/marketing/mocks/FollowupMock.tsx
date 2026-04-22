"use client";

import { useTranslations } from "next-intl";
import MockWindow from "./MockWindow";

/**
 * Feature 2 — next-step reminders. Two due-today items with pulsing
 * brand-blue dots + one blocked item in amber. The pulse is the
 * "nudge" motion; no timer or wall-clock logic — it's purely visual.
 */
interface FollowupMockProps {
  style?: React.CSSProperties;
  decorative?: boolean;
}

const richName = { b: (chunks: React.ReactNode) => <strong>{chunks}</strong> };

export default function FollowupMock({ style, decorative }: FollowupMockProps) {
  const t = useTranslations("marketing");
  return (
    <MockWindow title={t("mocks.followup.title")} style={style} decorative={decorative}>
      <div className="marketing-mock__row">
        <span className="marketing-mock__dot marketing-mock__dot--pulse" />
        <span className="marketing-mock__row-value">
          {t.rich("mocks.followup.row1", richName)}
        </span>
      </div>
      <div className="marketing-mock__row">
        <span className="marketing-mock__dot marketing-mock__dot--pulse" />
        <span className="marketing-mock__row-value">
          {t.rich("mocks.followup.row2", richName)}
        </span>
      </div>
      <div className="marketing-mock__row">
        <span className="marketing-mock__dot marketing-mock__dot--amber" />
        <span className="marketing-mock__row-value">
          {t.rich("mocks.followup.row3", richName)}
        </span>
      </div>
    </MockWindow>
  );
}
