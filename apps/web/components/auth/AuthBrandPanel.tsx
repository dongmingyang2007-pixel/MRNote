import { getTranslations } from "next-intl/server";

/**
 * AuthBrandPanel — right-column brand companion shown on >= lg screens
 * beside the auth form. RSC, no client JS.
 *
 * Philosophy: resist decoration. No concentric squares, no ring halos,
 * no radial gradients — the copy IS the design. Typography-first,
 * massive negative space, a single hairline separator. Think
 * Linear / Superhuman / Raycast, not a Bootstrap template.
 */
export async function AuthBrandPanel() {
  const t = await getTranslations("auth");

  const features = [
    { label: t("brandPanel.feature1") },
    { label: t("brandPanel.feature2") },
    { label: t("brandPanel.feature3") },
  ];

  return (
    <aside
      aria-hidden="true"
      className="relative hidden h-full w-full overflow-hidden border-l border-[var(--border)] bg-[var(--bg-surface)] lg:flex lg:flex-col lg:justify-center"
    >
      <div className="relative z-10 mx-auto w-full max-w-[440px] px-12 py-16">
        {/* Kicker */}
        <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-[var(--text-secondary)]">
          {t("brandPanel.kicker")}
        </p>

        {/* Headline — medium weight (600), tight tracking, generous
           line-height. Chinese typography renders 700 as borderline
           black/heavy; 600 keeps it elegant. */}
        <h2 className="font-display mt-6 text-[28px] font-semibold leading-[1.25] tracking-[-0.01em] text-[var(--text-primary)] md:text-[32px]">
          {t("brandPanel.title")}
        </h2>

        {/* Subtitle — normal weight, muted, comfortable line-height. */}
        <p className="mt-5 text-[15px] leading-relaxed text-[var(--text-secondary)]">
          {t("brandPanel.sub")}
        </p>

        {/* Single hairline separator — no stacks, no tint blocks. */}
        <div className="mt-12 h-px w-12 bg-[var(--text-primary)]/20" />

        {/* Feature list — no icon chips, no borders, no pills. Just
           numbered rows: quiet numerals + readable copy. */}
        <ol className="mt-10 space-y-6">
          {features.map((f, i) => (
            <li key={i} className="flex gap-5">
              <span className="mt-1 w-4 shrink-0 font-mono text-[12px] tabular-nums text-[var(--text-secondary)]">
                {String(i + 1).padStart(2, "0")}
              </span>
              <span className="text-[14px] leading-relaxed text-[var(--text-primary)]/85">
                {f.label}
              </span>
            </li>
          ))}
        </ol>

        {/* Testimonial — quiet, italic, margin-heavy. */}
        <p className="mt-16 text-[13px] italic leading-relaxed text-[var(--text-secondary)]/80">
          “{t("brandPanel.testimonialPlaceholder")}”
        </p>
      </div>
    </aside>
  );
}
