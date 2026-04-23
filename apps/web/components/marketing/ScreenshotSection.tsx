import { getTranslations } from "next-intl/server";

import LiveCanvasDemo from "./LiveCanvasDemo";

/**
 * ScreenshotSection — "look, the whole workspace" demonstration.
 *
 * The section chrome uses MRNote tokens (eyebrow + display heading +
 * secondary lead). The `.marketing-screenshot-stage` wrapper gives the
 * embedded LiveCanvasDemo a tinted radial-gradient backdrop with soft
 * dots — matching the `.canvas-stage` treatment used in the hero.
 *
 * LiveCanvasDemo's react-rnd logic is untouched; the wrapper only
 * reskins the surface around it.
 */
export default async function ScreenshotSection() {
  const t = await getTranslations("marketing");
  return (
    <section className="marketing-screenshot" id="screenshot">
      <div className="marketing-inner">
        <div className="marketing-screenshot__head">
          <span className="marketing-eyebrow">{t("screenshot.kicker")}</span>
          <h2 className="marketing-h2 marketing-screenshot__title">
            {t("screenshot.title")}
          </h2>
          <p className="marketing-lead marketing-screenshot__lead">
            {t("screenshot.sub")}
          </p>
        </div>

        <div className="marketing-screenshot-stage">
          <div
            className="marketing-screenshot-stage__dots"
            aria-hidden="true"
          />
          <LiveCanvasDemo />
        </div>
      </div>
    </section>
  );
}
