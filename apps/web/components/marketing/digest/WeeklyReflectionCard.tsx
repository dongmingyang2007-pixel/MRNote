import { ArrowRight, Check, Network, Plus, Sparkles } from "lucide-react";
import type { WeeklyReflectionMock } from "@/lib/marketing/role-content";
import Sparkline from "./Sparkline";

interface Props {
  data: WeeklyReflectionMock;
  locale: "zh" | "en";
  labels: {
    chromeTitle: string;
    saveAsPage: string;
    movesTitle: string;
    sparklineLabel: string;
    weekdayShort: [string, string, string, string, string, string, string];
  };
}

/** Weekly reflection card: headline + 4-stat grid + two columns (moves,
 *  options) + 7-day sparkline. Layout collapses to a single column below
 *  900px via CSS. */
export default function WeeklyReflectionCard({ data, locale, labels }: Props) {
  return (
    <article className="marketing-digest-card marketing-digest-card--weekly">
      <header className="marketing-digest-card__chrome">
        <span className="marketing-digest-card__chrome-icon">
          <Network size={14} aria-hidden="true" />
        </span>
        <span className="marketing-digest-card__chrome-title">{labels.chromeTitle}</span>
        <span className="marketing-digest-card__chrome-date">{data.range[locale]}</span>
        <span className="marketing-digest-card__chrome-spacer" aria-hidden="true" />
        <button type="button" className="marketing-digest-card__chrome-btn" disabled>
          <Plus size={12} aria-hidden="true" />
          <span>{labels.saveAsPage}</span>
        </button>
      </header>

      <div className="marketing-digest-card__body">
        <p className="marketing-weekly__headline">{data.headline[locale]}</p>

        <div className="marketing-weekly__stats" role="list">
          {data.stats.map((s) => (
            <div key={s.k[locale]} className="marketing-weekly__stat" role="listitem">
              <div className="marketing-weekly__stat-v">
                <span>{s.v}</span>
                {s.trend && (
                  <span
                    className={`marketing-weekly__stat-trend marketing-weekly__stat-trend--${
                      s.trendDir ?? "up"
                    }`}
                  >
                    {s.trend}
                  </span>
                )}
              </div>
              <div className="marketing-weekly__stat-k">{s.k[locale]}</div>
            </div>
          ))}
        </div>

        <div className="marketing-weekly__cols">
          <section>
            <h3 className="marketing-weekly__col-title">
              <Check size={13} aria-hidden="true" />
              {labels.movesTitle}
            </h3>
            <ul className="marketing-weekly__list">
              {data.moves.map((m, i) => (
                <li key={i}>{m[locale]}</li>
              ))}
            </ul>
          </section>

          <section>
            <h3 className="marketing-weekly__col-title">
              <Sparkles size={13} aria-hidden="true" />
              {data.ask[locale]}
            </h3>
            <div className="marketing-weekly__options" role="group">
              {data.options.map((o, i) => (
                <button key={i} type="button" className="marketing-weekly__option" disabled>
                  <span>{o[locale]}</span>
                  <ArrowRight size={12} aria-hidden="true" />
                </button>
              ))}
            </div>
          </section>
        </div>

        <Sparkline values={data.sparkline} label={labels.sparklineLabel} />
        <div className="marketing-weekly__sparkline-axis" aria-hidden="true">
          {labels.weekdayShort.map((d) => (
            <span key={d}>{d}</span>
          ))}
        </div>
      </div>
    </article>
  );
}
