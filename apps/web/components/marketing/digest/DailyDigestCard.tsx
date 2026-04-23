import { Sun, X } from "lucide-react";
import type { DailyDigestMock } from "@/lib/marketing/role-content";
import { DigestItemIcon } from "./digest-icons";

interface Props {
  data: DailyDigestMock;
  locale: "zh" | "en";
  labels: {
    chromeTitle: string;
    dismiss: string;
    startToday: string;
    saveInsight: string;
    arrivesAt: string;
  };
}

/** The daily digest card. Structure mirrors the prototype: a "browser chrome"
 *  header with timestamp + dismiss action, then a three-column grid of
 *  catch / today / insight blocks below a greeting line. */
export default function DailyDigestCard({ data, locale, labels }: Props) {
  return (
    <article className="marketing-digest-card marketing-digest-card--daily">
      <header className="marketing-digest-card__chrome">
        <span className="marketing-digest-card__chrome-icon">
          <Sun size={14} aria-hidden="true" />
        </span>
        <span className="marketing-digest-card__chrome-title">{labels.chromeTitle}</span>
        <span className="marketing-digest-card__chrome-date">{data.date[locale]}</span>
        <span className="marketing-digest-card__chrome-spacer" aria-hidden="true" />
        <button type="button" className="marketing-digest-card__chrome-btn" disabled>
          <X size={12} aria-hidden="true" />
          <span>{labels.dismiss}</span>
        </button>
      </header>

      <div className="marketing-digest-card__body">
        <p className="marketing-digest-card__greeting">{data.greeting[locale]}</p>

        <div className="marketing-digest-card__grid">
          {data.blocks.map((block, idx) => (
            <section
              key={`${block.kind}-${idx}`}
              className={`marketing-digest-block marketing-digest-block--${block.kind}`}
            >
              <h3 className="marketing-digest-block__title">
                <DigestItemIcon
                  name={block.kind === "catch" ? "note" : block.kind === "today" ? "check" : "sparkles"}
                />
                {block.title[locale]}
              </h3>

              {block.kind === "insight" ? (
                <p className="marketing-digest-block__body">{block.body[locale]}</p>
              ) : (
                <ul className="marketing-digest-block__list">
                  {block.items.map((item, j) => (
                    <li key={j}>
                      <span className="marketing-digest-block__item-icon">
                        <DigestItemIcon name={item.icon} size={12} />
                      </span>
                      <span className="marketing-digest-block__item-body">
                        <span className="marketing-digest-block__item-label">{item.label[locale]}</span>
                        <span className="marketing-digest-block__item-tag">{item.tag[locale]}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          ))}
        </div>

        <footer className="marketing-digest-card__foot">
          <span className="marketing-digest-card__foot-pill">{labels.startToday}</span>
          <span className="marketing-digest-card__foot-ghost">{labels.saveInsight}</span>
          <span className="marketing-digest-card__foot-spacer" aria-hidden="true" />
          <span className="marketing-digest-card__foot-note">{labels.arrivesAt}</span>
        </footer>
      </div>
    </article>
  );
}
