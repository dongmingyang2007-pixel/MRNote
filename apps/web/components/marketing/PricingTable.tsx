"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { Check } from "lucide-react";
import clsx from "clsx";

type Cycle = "monthly" | "yearly";

interface PlanDef {
  key: "free" | "pro" | "power" | "team";
  highlight?: boolean;
  featureCount: number;
  register: (cycle: Cycle) => string;
}

const PLANS: PlanDef[] = [
  {
    key: "free",
    featureCount: 3,
    register: () => "/register",
  },
  {
    key: "pro",
    highlight: true,
    featureCount: 4,
    register: (cycle) => `/register?plan=pro&cycle=${cycle}`,
  },
  {
    key: "power",
    featureCount: 4,
    register: (cycle) => `/register?plan=power&cycle=${cycle}`,
  },
  {
    key: "team",
    featureCount: 3,
    register: (cycle) => `/register?plan=team&cycle=${cycle}`,
  },
];

export default function PricingTable() {
  const t = useTranslations("marketing");
  const [cycle, setCycle] = useState<Cycle>("monthly");

  const cadenceKeyFor = (plan: PlanDef["key"]) => {
    if (plan === "free") return "plan.free.cadence";
    return `plan.${plan}.cadence.${cycle}`;
  };

  return (
    <section className="marketing-section" style={{ paddingTop: 24 }}>
      <div
        className="marketing-inner marketing-inner--wide"
        style={{ margin: "0 auto", textAlign: "center" }}
      >
        <div
          aria-hidden={cycle !== "yearly"}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "4px 12px",
            borderRadius: "var(--radius-full)",
            background: "rgba(15, 118, 255, 0.1)",
            color: "var(--brand-v2)",
            fontSize: "0.72rem",
            fontWeight: 600,
            letterSpacing: "0.04em",
            textTransform: "uppercase",
            marginBottom: 14,
            opacity: cycle === "yearly" ? 1 : 0,
            transform:
              cycle === "yearly" ? "translateY(0)" : "translateY(4px)",
            transition:
              "opacity var(--motion-base) var(--motion-ease), transform var(--motion-base) var(--motion-ease)",
            pointerEvents: cycle === "yearly" ? "auto" : "none",
          }}
        >
          {t("pricing.cycle.save")}
        </div>
        <div
          role="group"
          aria-label={t("pricing.kicker")}
          style={{
            display: "inline-flex",
            padding: 4,
            borderRadius: "var(--radius-full)",
            border: "1px solid var(--border)",
            background: "var(--bg-base)",
            margin: "0 auto 40px",
          }}
        >
          <button
            type="button"
            onClick={() => setCycle("monthly")}
            className={clsx("marketing-btn", {
              "marketing-btn--primary": cycle === "monthly",
              "marketing-btn--secondary": cycle !== "monthly",
            })}
            style={{
              border: "0",
              boxShadow: cycle === "monthly" ? undefined : "none",
              padding: "8px 18px",
              fontSize: "0.9rem",
              background: cycle === "monthly" ? "var(--brand-v2)" : "transparent",
              color: cycle === "monthly" ? "#fff" : "var(--text-secondary)",
            }}
            aria-pressed={cycle === "monthly"}
          >
            {t("pricing.cycle.monthly")}
          </button>
          <button
            type="button"
            onClick={() => setCycle("yearly")}
            className={clsx("marketing-btn", {
              "marketing-btn--primary": cycle === "yearly",
              "marketing-btn--secondary": cycle !== "yearly",
            })}
            style={{
              border: "0",
              boxShadow: cycle === "yearly" ? undefined : "none",
              padding: "8px 18px",
              fontSize: "0.9rem",
              background: cycle === "yearly" ? "var(--brand-v2)" : "transparent",
              color: cycle === "yearly" ? "#fff" : "var(--text-secondary)",
              gap: 8,
            }}
            aria-pressed={cycle === "yearly"}
          >
            {t("pricing.cycle.yearly")}
            <span
              style={{
                fontSize: "0.72rem",
                background: cycle === "yearly" ? "rgba(255,255,255,0.22)" : "rgba(15,118,255,0.12)",
                color: cycle === "yearly" ? "#fff" : "var(--brand-v2)",
                padding: "2px 6px",
                borderRadius: "var(--radius-full)",
                fontWeight: 600,
              }}
            >
              {t("pricing.cycle.save")}
            </span>
          </button>
        </div>

        <div
          className="marketing-pricing-grid marketing-pricing-grid--4"
          style={{ alignItems: "stretch" }}
        >
          {PLANS.map((plan) => {
            const priceKey =
              plan.key === "free"
                ? "plan.free.price.monthly"
                : `plan.${plan.key}.price.${cycle}`;
            return (
              <div
                key={plan.key}
                className={clsx("marketing-plan-card", {
                  "marketing-plan-card--highlight": plan.highlight,
                })}
              >
                {plan.highlight && (
                  <span className="marketing-plan-card__badge">
                    {t("plan.pro.badge")}
                  </span>
                )}
                <div>
                  <div
                    className="font-display tracking-tight"
                    style={{
                      fontSize: "1.125rem",
                      fontWeight: 600,
                      color: "var(--text-primary)",
                    }}
                  >
                    {t(`plan.${plan.key}.name`)}
                  </div>
                  <div
                    className="marketing-body"
                    style={{ fontSize: "0.88rem", marginTop: 4 }}
                  >
                    {t(`plan.${plan.key}.tagline`)}
                  </div>
                </div>
                <div>
                  <span className="marketing-plan-card__price">{t(priceKey)}</span>
                  <span className="marketing-plan-card__cadence">
                    {t(cadenceKeyFor(plan.key))}
                  </span>
                </div>
                <ul className="marketing-plan-card__features">
                  {Array.from({ length: plan.featureCount }).map((_, idx) => (
                    <li key={idx} className="marketing-plan-card__feature">
                      <Check
                        size={16}
                        strokeWidth={2.4}
                        color="var(--brand-v2)"
                        style={{ marginTop: 3, flexShrink: 0 }}
                      />
                      <span>{t(`plan.${plan.key}.feat.${idx}`)}</span>
                    </li>
                  ))}
                </ul>
                <div style={{ marginTop: "auto", paddingTop: 12 }}>
                  <Link
                    href={plan.register(cycle)}
                    className={clsx("marketing-btn", {
                      "marketing-btn--primary": plan.highlight,
                      "marketing-btn--secondary": !plan.highlight,
                    })}
                    style={{ width: "100%" }}
                  >
                    {t(`plan.${plan.key}.cta`)}
                  </Link>
                  {plan.key === "pro" && (
                    <div
                      className="marketing-body"
                      style={{
                        fontSize: "0.8rem",
                        marginTop: 10,
                        textAlign: "center",
                      }}
                    >
                      {t("plan.pro.trial")}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
