"use client";

import { useTranslations } from "next-intl";
import MockWindow from "./MockWindow";

/**
 * Feature 3 — weekly reflection. Monday digest preview. Three compressed
 * bullets giving the feeling of a "weekly at a glance". No motion —
 * this one is intentionally calm to contrast with the pulsing
 * FollowupMock.
 */
interface DigestMockProps {
  style?: React.CSSProperties;
  decorative?: boolean;
}

export default function DigestMock({ style, decorative }: DigestMockProps) {
  const t = useTranslations("marketing");
  return (
    <MockWindow title={t("mocks.digest.title")} style={style} decorative={decorative}>
      <div className="marketing-mock__row">
        <span className="marketing-mock__row-label">{t("mocks.digest.row1.label")}</span>
        <span className="marketing-mock__row-value">{t("mocks.digest.row1.value")}</span>
      </div>
      <div className="marketing-mock__row">
        <span className="marketing-mock__row-label">{t("mocks.digest.row2.label")}</span>
        <span className="marketing-mock__row-value">{t("mocks.digest.row2.value")}</span>
      </div>
      <div className="marketing-mock__row">
        <span className="marketing-mock__row-label">{t("mocks.digest.row3.label")}</span>
        <span className="marketing-mock__row-value">{t("mocks.digest.row3.value")}</span>
      </div>
    </MockWindow>
  );
}
