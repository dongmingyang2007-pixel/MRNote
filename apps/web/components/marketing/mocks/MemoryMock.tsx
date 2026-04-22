"use client";

import { useTranslations } from "next-intl";
import MockWindow from "./MockWindow";

/**
 * Feature 1 — "persistent memory". Three memory rows extracted from a
 * notebook workstream. The last row ends with a blinking caret to
 * suggest it's being written in real-time, reinforcing the
 * "auto-extracted" promise of the feature.
 */
interface MemoryMockProps {
  style?: React.CSSProperties;
  decorative?: boolean;
}

export default function MemoryMock({ style, decorative }: MemoryMockProps) {
  const t = useTranslations("marketing");
  return (
    <MockWindow title={t("mocks.memory.title")} style={style} decorative={decorative}>
      <div className="marketing-mock__row">
        <span className="marketing-mock__row-label">{t("mocks.memory.row1.label")}</span>
        <span className="marketing-mock__row-value">{t("mocks.memory.row1.value")}</span>
      </div>
      <div className="marketing-mock__row">
        <span className="marketing-mock__row-label">{t("mocks.memory.row2.label")}</span>
        <span className="marketing-mock__row-value">{t("mocks.memory.row2.value")}</span>
      </div>
      <div className="marketing-mock__row">
        <span className="marketing-mock__row-label">{t("mocks.memory.row3.label")}</span>
        <span className="marketing-mock__row-value">
          {t("mocks.memory.row3.value")}
          <span className="marketing-mock__caret" />
        </span>
      </div>
    </MockWindow>
  );
}
