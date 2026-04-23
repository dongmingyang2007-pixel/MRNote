import HeroAnimatedClient from "./HeroAnimatedClient";
import HeroCanvasStage from "./HeroCanvasStage";
import HeroPersonaCopy from "./HeroPersonaCopy";
import HeroRoleBadge from "./HeroRoleBadge";

interface HeroSectionProps {
  locale?: "zh" | "en";
}

export default async function HeroSection({ locale = "zh" }: HeroSectionProps = {}) {
  return (
    <section className="marketing-hero">
      <HeroAnimatedClient>
        <div className="marketing-hero__grid">
          <div className="marketing-fade-in">
            <HeroRoleBadge locale={locale} />
            <HeroPersonaCopy locale={locale} />
          </div>

          <div className="marketing-hero__demo-wrap marketing-fade-in marketing-fade-in--delay-2">
            <HeroCanvasStage />
          </div>
        </div>
      </HeroAnimatedClient>
    </section>
  );
}
