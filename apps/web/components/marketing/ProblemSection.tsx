import { getTranslations } from "next-intl/server";
import { FileText, Search, UserX } from "lucide-react";

const ICONS = {
  notes: FileText,
  recall: Search,
  drops: UserX,
} as const;

type ItemKey = 1 | 2 | 3;

export default async function ProblemSection() {
  const t = await getTranslations("marketing");
  const items: ItemKey[] = [1, 2, 3];

  return (
    <section className="marketing-section" id="problem">
      <div className="marketing-inner">
        <div className="marketing-inner--narrow" style={{ textAlign: "center", margin: "0 auto" }}>
          <span className="marketing-eyebrow">{t("problem.kicker")}</span>
          <h2 className="marketing-h2">{t("problem.title")}</h2>
        </div>

        <div className="marketing-grid-3">
          {items.map((i) => {
            const iconKey = t(`problem.item${i}.icon`) as keyof typeof ICONS;
            const Icon = ICONS[iconKey] ?? FileText;
            return (
              <div key={i} className="marketing-problem-card">
                <div className="marketing-problem-card__icon">
                  <Icon size={20} strokeWidth={2} />
                </div>
                <h3
                  style={{
                    fontSize: "1.125rem",
                    fontWeight: 600,
                    color: "var(--text-primary)",
                  }}
                >
                  {t(`problem.item${i}.title`)}
                </h3>
                <p className="marketing-body">{t(`problem.item${i}.body`)}</p>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
