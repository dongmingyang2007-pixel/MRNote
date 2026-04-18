"use client";

import { Check } from "lucide-react";
import { useTranslations } from "next-intl";
import { apiPost } from "@/lib/api";

export interface PlanDescriptor {
  id: "free" | "pro" | "power" | "team";
  name: string;
  monthlyPrice: number | null;
  yearlyPrice: number | null;
  features: string[];
}

interface Props {
  plan: PlanDescriptor;
  cycle: "monthly" | "yearly";
  isCurrent: boolean;
}

export default function PlanCard({ plan, cycle, isCurrent }: Props) {
  const t = useTranslations("billing");
  const price = cycle === "monthly" ? plan.monthlyPrice : plan.yearlyPrice;

  const handleUpgrade = async () => {
    if (plan.id === "free") return;
    try {
      const data = await apiPost<{ checkout_url: string }>(
        "/api/v1/billing/checkout",
        { plan: plan.id, cycle },
      );
      window.location.href = data.checkout_url;
    } catch (e) {
      console.error("checkout failed", e);
    }
  };

  return (
    <div
      className={`plan-card${isCurrent ? " plan-card--current" : ""}`}
      data-testid={`plan-card-${plan.id}`}
    >
      <h2 className="plan-card__name">{plan.name}</h2>
      <div className="plan-card__price">
        {price === null ? (
          t("plan.price.free")
        ) : (
          <>
            ${price}
            <span className="plan-card__cycle">/{cycle === "monthly" ? t("plan.price.monthly") : t("plan.price.yearly")}</span>
          </>
        )}
      </div>
      <ul className="plan-card__features">
        {plan.features.map((f, i) => (
          <li key={i}>
            <Check size={14} /> {f}
          </li>
        ))}
      </ul>
      {isCurrent ? (
        <div className="plan-card__current-label">{t("plan.currentLabel")}</div>
      ) : plan.id === "free" ? null : (
        <button
          type="button"
          onClick={handleUpgrade}
          className="plan-card__upgrade"
          data-testid={`plan-card-${plan.id}-upgrade`}
        >
          {t("upgrade.button")}
        </button>
      )}
    </div>
  );
}
