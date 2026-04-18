"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { apiGet } from "@/lib/api";
import PlanCard, { type PlanDescriptor } from "./PlanCard";

const PLAN_PRICES = {
  free: { monthly: null, yearly: null },
  pro: { monthly: 10, yearly: 102 },
  power: { monthly: 25, yearly: 255 },
  team: { monthly: 15, yearly: 153 },
} as const;

export default function PlansGrid() {
  const t = useTranslations("billing");
  const [cycle, setCycle] = useState<"monthly" | "yearly">("monthly");
  const [currentPlan, setCurrentPlan] = useState<string>("free");

  useEffect(() => {
    void apiGet<{ plan: string }>("/api/v1/billing/me")
      .then((r) => setCurrentPlan(r.plan))
      .catch(() => {});
  }, []);

  const PLAN_FEATURES: Record<PlanDescriptor["id"], string[]> = {
    free: [
      t("plan.features.free.0"),
      t("plan.features.free.1"),
      t("plan.features.free.2"),
      t("plan.features.free.3"),
    ],
    pro: [
      t("plan.features.pro.0"),
      t("plan.features.pro.1"),
      t("plan.features.pro.2"),
      t("plan.features.pro.3"),
      t("plan.features.pro.4"),
      t("plan.features.pro.5"),
      t("plan.features.pro.6"),
    ],
    power: [
      t("plan.features.power.0"),
      t("plan.features.power.1"),
      t("plan.features.power.2"),
      t("plan.features.power.3"),
    ],
    team: [
      t("plan.features.team.0"),
      t("plan.features.team.1"),
      t("plan.features.team.2"),
      t("plan.features.team.3"),
      t("plan.features.team.4"),
    ],
  };

  const plans: PlanDescriptor[] = (
    ["free", "pro", "power", "team"] as const
  ).map((id) => ({
    id,
    name: t(`plan.${id}.name`),
    monthlyPrice: PLAN_PRICES[id].monthly,
    yearlyPrice: PLAN_PRICES[id].yearly,
    features: PLAN_FEATURES[id],
  }));

  return (
    <section className="plans-grid">
      <div className="plans-grid__cycle-toggle">
        <button
          type="button"
          aria-pressed={cycle === "monthly"}
          onClick={() => setCycle("monthly")}
          data-testid="cycle-monthly"
        >
          {t("plans.cycle.monthly")}
        </button>
        <button
          type="button"
          aria-pressed={cycle === "yearly"}
          onClick={() => setCycle("yearly")}
          data-testid="cycle-yearly"
        >
          {t("plans.cycle.yearly")}
        </button>
      </div>
      <div className="plans-grid__cards">
        {plans.map((p) => (
          <PlanCard
            key={p.id}
            plan={p}
            cycle={cycle}
            isCurrent={currentPlan === p.id}
          />
        ))}
      </div>
    </section>
  );
}
