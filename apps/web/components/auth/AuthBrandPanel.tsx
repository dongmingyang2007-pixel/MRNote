import { getTranslations } from "next-intl/server";
import { Brain, Bell, Sparkles } from "lucide-react";

/**
 * AuthBrandPanel — right-column brand companion shown on >= lg screens
 * beside the auth form. RSC, no client JS, copy pulled from auth.brandPanel.*.
 */
export async function AuthBrandPanel() {
  const t = await getTranslations("auth");

  const features = [
    { Icon: Brain, label: t("brandPanel.feature1") },
    { Icon: Bell, label: t("brandPanel.feature2") },
    { Icon: Sparkles, label: t("brandPanel.feature3") },
  ];

  return (
    <aside
      aria-hidden="true"
      className="relative hidden h-full w-full overflow-hidden border-l border-[var(--border)] bg-[var(--bg-surface)] lg:flex lg:flex-col lg:items-center lg:justify-center"
    >
      {/* Ambient brand tint wash */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(120% 80% at 90% 0%, rgba(15, 118, 255, 0.08) 0%, rgba(15, 118, 255, 0) 55%)",
        }}
      />

      {/* Geometric decoration: stacked concentric rounded squares, anchored top-right */}
      <div className="pointer-events-none absolute -right-24 -top-24 h-[360px] w-[360px]">
        <div className="absolute inset-0 rounded-[48px] border border-[var(--brand-v2)]/15" />
        <div className="absolute inset-8 rounded-[42px] border border-[var(--brand-v2)]/18" />
        <div className="absolute inset-16 rounded-[36px] border border-[var(--brand-v2)]/20" />
        <div className="absolute inset-24 rounded-[30px] border border-[var(--brand-v2)]/25" />
        <div className="absolute inset-32 rounded-[24px] bg-[var(--brand-v2)]/10" />
      </div>

      {/* Subtle hairline decoration, anchored bottom-left */}
      <div className="pointer-events-none absolute -bottom-20 -left-20 h-[240px] w-[240px]">
        <div className="absolute inset-0 rounded-full border border-[var(--brand-v2)]/10" />
        <div className="absolute inset-10 rounded-full border border-[var(--brand-v2)]/10" />
      </div>

      {/* Content */}
      <div className="relative z-10 w-full max-w-md px-10 py-16">
        <p className="text-xs font-medium uppercase tracking-widest text-[var(--text-secondary)]">
          {t("brandPanel.kicker")}
        </p>

        <h2 className="font-display mt-5 text-3xl font-bold leading-tight tracking-tight text-[var(--text-primary)] md:text-4xl">
          {t("brandPanel.title")}
        </h2>

        <p className="mt-4 text-sm leading-relaxed text-[var(--text-secondary)] md:text-base">
          {t("brandPanel.sub")}
        </p>

        <div className="my-8 h-px w-full bg-[var(--border)]" />

        <ul className="space-y-4">
          {features.map(({ Icon, label }, i) => (
            <li
              key={i}
              className="flex items-start gap-3 text-sm leading-relaxed text-[var(--text-primary)]"
            >
              <span
                className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--brand-v2)]/10 text-[var(--brand-v2)]"
                aria-hidden="true"
              >
                <Icon className="h-3.5 w-3.5" strokeWidth={2.25} />
              </span>
              <span>{label}</span>
            </li>
          ))}
        </ul>

        <div className="my-8 h-px w-full bg-[var(--border)]" />

        <figure className="border-l-2 border-[var(--brand-v2)]/40 pl-4">
          <blockquote className="text-sm italic leading-relaxed text-[var(--text-secondary)]">
            &ldquo;{t("brandPanel.testimonialPlaceholder")}&rdquo;
          </blockquote>
        </figure>
      </div>
    </aside>
  );
}
