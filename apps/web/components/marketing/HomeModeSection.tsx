import { getTranslations } from "next-intl/server";
import { BookOpenCheck, GitBranch, ListTodo, Sparkles } from "lucide-react";

const MODES = [
  { key: "capture", Icon: BookOpenCheck },
  { key: "connect", Icon: GitBranch },
  { key: "continue", Icon: ListTodo },
  { key: "review", Icon: Sparkles },
] as const;

export default async function HomeModeSection() {
  const t = await getTranslations("marketing");

  return (
    <section className="marketing-mode" aria-labelledby="marketing-mode-title">
      <div className="marketing-mode__inner">
        <div className="marketing-mode__intro">
          <span className="marketing-eyebrow">{t("mode.eyebrow")}</span>
          <h2 id="marketing-mode-title" className="marketing-mode__title">
            {t("mode.title")}
          </h2>
        </div>
        <div className="marketing-mode__rail">
          {MODES.map(({ key, Icon }, index) => (
            <div key={key} className="marketing-mode__item">
              <div className="marketing-mode__item-top">
                <span className="marketing-mode__step">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <Icon size={18} strokeWidth={1.8} aria-hidden="true" />
              </div>
              <h3>{t(`mode.${key}.title`)}</h3>
              <p>{t(`mode.${key}.body`)}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
