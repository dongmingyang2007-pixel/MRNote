import HeroAnimatedClient from "./HeroAnimatedClient";
import HeroPersonaCopy from "./HeroPersonaCopy";

interface HeroSectionProps {
  locale?: "zh" | "en";
}

/**
 * Hero shell — centered single-column layout (not split 2-col).
 * Soft teal/orange radial glow + faded grid in the background; the
 * persona pill-switch, kicker pill, split title, sub, CTAs, footer
 * dots and canvas stage all live inside the client `HeroPersonaCopy`
 * so a single state drives copy + focused window.
 */
export default function HeroSection({ locale = "zh" }: HeroSectionProps = {}) {
  return (
    <section className="marketing-hero">
      <div className="marketing-hero__bg" aria-hidden="true" />
      <div className="marketing-hero__grid-bg" aria-hidden="true" />
      <HeroAnimatedClient>
        <div className="marketing-hero__inner marketing-fade-in">
          <HeroPersonaCopy locale={locale} />
        </div>
      </HeroAnimatedClient>
    </section>
  );
}
