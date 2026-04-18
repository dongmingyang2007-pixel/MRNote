import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import { ArrowRight, PlayCircle } from "lucide-react";
import HeroAnimatedClient from "./HeroAnimatedClient";

export default async function HeroSection() {
  const t = await getTranslations("marketing");
  return (
    <section className="marketing-hero">
      <HeroAnimatedClient>
        <div className="marketing-hero__grid">
          <div className="marketing-fade-in">
            <span className="marketing-eyebrow">{t("hero.kicker")}</span>
            <h1 className="marketing-h1 font-display" style={{ marginBottom: 24 }}>
              {t("hero.title")}
            </h1>
            <p className="marketing-lead" style={{ maxWidth: 580 }}>
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

          <div className="marketing-hero__demo marketing-fade-in marketing-fade-in--delay-2">
            <div
              style={{
                fontSize: "0.95rem",
                fontWeight: 600,
                color: "var(--text-primary)",
                marginBottom: 8,
              }}
            >
              {t("hero.demo.placeholder.title")}
            </div>
            <div style={{ fontSize: "0.85rem" }}>
              {t("hero.demo.placeholder.hint")}
            </div>
          </div>
        </div>
      </HeroAnimatedClient>
    </section>
  );
}
