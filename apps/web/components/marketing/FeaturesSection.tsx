import { getTranslations } from "next-intl/server";
import { Check } from "lucide-react";

import MemoryMock from "./mocks/MemoryMock";
import FollowupMock from "./mocks/FollowupMock";
import DigestMock from "./mocks/DigestMock";

// Map feature index → mock component. Kept here (not in mocks/) so
// the feature→mock pairing is visible at the call site.
const FEATURE_MOCKS = {
  1: MemoryMock,
  2: FollowupMock,
  3: DigestMock,
} as const;

// Chrome file-name captions are derived from translations of the mock
// titles — the prototype shows a faux "page 12 · notebook" header above
// each demo window. We fall back to a generic label when i18n is missing.
const CHROME_LABELS: Record<1 | 2 | 3, { label: string; path: string }> = {
  1: { label: "memory", path: "notebook · persistent" },
  2: { label: "canvas", path: "notebook · page 12" },
  3: { label: "study", path: "notebook · weekly" },
};

type FeatureKey = 1 | 2 | 3;

/**
 * FeaturesSection — mirrors `.feature-row` in MRNote sections.css.
 *
 * Each feature is a full-bleed row with alternating bg tones
 * (`--mkt-bg-base` / `--mkt-bg-surface`) and reversed columns on even
 * rows. The right-side "demo frame" wraps the existing mocks in a 4:3
 * framed viewport (dotted canvas + chrome bar) to match the prototype
 * scaffolding without disturbing the mock internals.
 */
export default async function FeaturesSection() {
  const t = await getTranslations("marketing");
  const features: FeatureKey[] = [1, 2, 3];

  return (
    <div id="features">
      {features.map((i) => {
        const Mock = FEATURE_MOCKS[i];
        const chrome = CHROME_LABELS[i];
        const reverse = i % 2 === 0;
        return (
          <section
            key={i}
            className={`marketing-feature-row${reverse ? " marketing-feature-row--reverse" : ""}`}
          >
            <div className="marketing-feature-row__inner">
              <div className="marketing-feature-row__copy">
                <span className="marketing-eyebrow">
                  {t(`feature${i}.eyebrow`)}
                </span>
                <h2 className="marketing-h2 marketing-feature-row__title">
                  {t(`feature${i}.title`)}
                </h2>
                <p className="marketing-feature-row__body">
                  {t(`feature${i}.body`)}
                </p>
                <ul className="marketing-feature-row__bullets">
                  <li>
                    <Check
                      size={16}
                      strokeWidth={2.4}
                      aria-hidden="true"
                    />
                    <span>{t(`feature${i}.bullets.0`)}</span>
                  </li>
                  <li>
                    <Check
                      size={16}
                      strokeWidth={2.4}
                      aria-hidden="true"
                    />
                    <span>{t(`feature${i}.bullets.1`)}</span>
                  </li>
                  <li>
                    <Check
                      size={16}
                      strokeWidth={2.4}
                      aria-hidden="true"
                    />
                    <span>{t(`feature${i}.bullets.2`)}</span>
                  </li>
                </ul>
              </div>
              <div className="marketing-feature-row__media">
                <div className="marketing-demo-frame">
                  <div
                    className="marketing-demo-frame__dots"
                    aria-hidden="true"
                  />
                  <div className="marketing-demo-frame__chrome">
                    <strong>{chrome.label}</strong>
                    <span>/ {chrome.path}</span>
                  </div>
                  <div className="marketing-demo-frame__mock">
                    <Mock />
                  </div>
                </div>
              </div>
            </div>
          </section>
        );
      })}
    </div>
  );
}
