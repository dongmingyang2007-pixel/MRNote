import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import { ArrowRight, PlayCircle } from "lucide-react";
import HeroAnimatedClient from "./HeroAnimatedClient";
import HeroCanvasStage from "./HeroCanvasStage";
import HeroRoleBadge from "./HeroRoleBadge";

interface HeroSectionProps {
  locale?: "zh" | "en";
}

export default async function HeroSection({ locale = "zh" }: HeroSectionProps = {}) {
  const t = await getTranslations("marketing");
  return (
    <section className="marketing-hero">
      <HeroAnimatedClient>
        <div className="marketing-hero__grid">
          <div className="marketing-fade-in">
            <HeroRoleBadge locale={locale} />
            <span className="marketing-eyebrow mb-4">{t("hero.kicker")}</span>
            <h1
              className="marketing-h1 font-display tracking-tight text-4xl md:text-6xl lg:text-7xl mb-6 md:mb-8"
            >
              {t("hero.title")}
            </h1>
            <p
              className="marketing-lead text-lg md:text-xl leading-relaxed mb-8 md:mb-10"
              style={{ maxWidth: 580 }}
            >
              {t("hero.sub")}
            </p>
            <div className="marketing-hero__cta-row">
              <Link
                href="/register"
                className="marketing-btn marketing-btn--primary marketing-btn--lg"
              >
                {t("hero.cta.primary")}
                <ArrowRight size={16} />
              </Link>
              <Link
                href="/#features"
                className="marketing-btn marketing-btn--secondary marketing-btn--lg"
              >
                <PlayCircle size={16} />
                {t("hero.cta.secondary")}
              </Link>
            </div>
          </div>

          <div className="marketing-hero__demo-wrap marketing-fade-in marketing-fade-in--delay-2">
            <HeroCanvasStage />
          </div>
        </div>
      </HeroAnimatedClient>
    </section>
  );
}
