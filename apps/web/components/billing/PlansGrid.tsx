"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import PlanCard, { type PlanDescriptor } from "./PlanCard";

const PLAN_FEATURES: Record<PlanDescriptor["id"], string[]> = {
  free: [
    "1 notebook", "50 pages", "1 study asset",
    "50 AI actions / month",
  ],
  pro: [
    "Unlimited notebooks", "500 pages", "20 study assets",
    "1,000 AI actions / month", "Daily digest", "Voice", "Book upload",
  ],
  power: [
    "Everything in Pro", "Unlimited pages & study assets",
    "10,000 AI actions / month", "Advanced memory insights",
  ],
  team: [
    "Everything in Power", "Per-seat pricing",
    "Shared workspace", "Team memory views", "Admin billing",
  ],
};

const PLAN_PRICES = {
  free: { monthly: null, yearly: null },
  pro: { monthly: 10, yearly: 102 },
  power: { monthly: 25, yearly: 255 },
  team: { monthly: 15, yearly: 153 },
} as const;

export default function PlansGrid() {
  const [cycle, setCycle] = useState<"monthly" | "yearly">("monthly");
  const [currentPlan, setCurrentPlan] = useState<string>("free");

  useEffect(() => {
    void apiGet<{ plan: string }>("/api/v1/billing/me")
      .then((r) => setCurrentPlan(r.plan))
      .catch(() => {});
  }, []);

  const plans: PlanDescriptor[] = (
    ["free", "pro", "power", "team"] as const
  ).map((id) => ({
    id,
    name: id.charAt(0).toUpperCase() + id.slice(1),
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
          Monthly
        </button>
        <button
          type="button"
          aria-pressed={cycle === "yearly"}
          onClick={() => setCycle("yearly")}
          data-testid="cycle-yearly"
        >
          Yearly (15% off)
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
