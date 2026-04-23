import { getTranslations } from "next-intl/server";
import DigestSectionClient from "./digest/DigestSectionClient";

interface Props {
  locale?: "zh" | "en";
}

/** Server wrapper that renders the section header (eyebrow / title / lead)
 *  and delegates the per-role tabbed card to DigestSectionClient. */
export default async function DigestSection({ locale = "zh" }: Props = {}) {
  const t = await getTranslations("marketing.digest");

  return (
    <section className="marketing-digest" id="digest">
      <div className="marketing-digest__inner">
        <header className="marketing-digest__head">
          <span className="marketing-eyebrow">{t("eyebrow")}</span>
          <h2 className="marketing-digest__title font-display">
            {t("title.lineA")}
            <br />
            {t("title.lineBPrefix")}
            <em className="marketing-digest__title-em">{t("title.lineBEm")}</em>
            {t("title.lineBSuffix")}
          </h2>
          <p className="marketing-digest__lead">{t("lead")}</p>
        </header>

        <DigestSectionClient locale={locale} />
      </div>
    </section>
  );
}
