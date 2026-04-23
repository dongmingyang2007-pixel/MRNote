import { getTranslations } from "next-intl/server";

type ItemKey = 1 | 2 | 3;

/**
 * ProblemSection — mirrors `.problem` in MRNote sections.css.
 *
 * Layout: 2-col grid (header copy | numbered items list). Each item is a
 * `44px 1fr` grid with a mono number token in teal, a heavy-tracking
 * title, and a secondary body. Items are separated by top borders so the
 * list reads as a documentary chronicle of pain points.
 */
export default async function ProblemSection() {
  const t = await getTranslations("marketing");
  const items: ItemKey[] = [1, 2, 3];

  return (
    <section className="marketing-problem" id="problem">
      <div className="marketing-problem__grid">
        <div className="marketing-problem__header">
          <span className="marketing-eyebrow">{t("problem.kicker")}</span>
          <h2 className="marketing-h2 marketing-problem__title">
            {t("problem.title")}
          </h2>
        </div>

        <div className="marketing-problem__list">
          {items.map((i) => (
            <div key={i} className="marketing-problem__item">
              <span className="marketing-problem__item-num" aria-hidden="true">
                {String(i).padStart(2, "0")}
              </span>
              <div>
                <h3 className="marketing-problem__item-title">
                  {t(`problem.item${i}.title`)}
                </h3>
                <p className="marketing-problem__item-body">
                  {t(`problem.item${i}.body`)}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
