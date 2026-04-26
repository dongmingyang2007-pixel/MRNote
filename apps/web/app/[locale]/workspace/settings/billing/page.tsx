"use client";

import "@/styles/billing.css";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import CurrentSubscription from "@/components/billing/CurrentSubscription";
import UsageMeter from "@/components/billing/UsageMeter";
import PlansGrid from "@/components/billing/PlansGrid";
import billingSDK, { type PlanId } from "@/lib/billing-sdk";
import {
  clearPendingCheckoutPlan,
  isPaidPlanId,
  readStoredPendingCheckoutPlan,
} from "@/lib/pending-checkout";

type CheckoutStatus = "success" | "cancel" | null;

function normalizeCheckoutStatus(value: string | null): CheckoutStatus {
  return value === "success" || value === "cancel" ? value : null;
}

export default function BillingSettingsPage() {
  const t = useTranslations("billing");
  const [checkoutStatus] = useState<CheckoutStatus>(() => {
    if (typeof window === "undefined") return null;
    return normalizeCheckoutStatus(
      new URLSearchParams(window.location.search).get("status"),
    );
  });
  const [confirmedPlan, setConfirmedPlan] = useState<PlanId | null>(null);
  const [loadingConfirmation, setLoadingConfirmation] = useState(false);

  useEffect(() => {
    const status = checkoutStatus;

    if (status === "cancel") {
      clearPendingCheckoutPlan();
      return;
    }
    if (status !== "success") {
      return;
    }

    const storedPlan = readStoredPendingCheckoutPlan();
    if (isPaidPlanId(storedPlan?.plan)) {
      setConfirmedPlan(storedPlan.plan);
    }

    setLoadingConfirmation(true);
    void billingSDK
      .getMe()
      .then((summary) => {
        if (isPaidPlanId(summary.plan)) {
          setConfirmedPlan(summary.plan);
          clearPendingCheckoutPlan();
        }
      })
      .catch(() => undefined)
      .finally(() => setLoadingConfirmation(false));
  }, [checkoutStatus]);

  const confirmedPlanLabel = confirmedPlan
    ? t(`plan.${confirmedPlan}.name`)
    : null;

  return (
    <div className="billing-page" data-testid="billing-page">
      <h1 className="billing-page__title">{t("page.title")}</h1>
      {checkoutStatus === "success" && (
        <div
          className="billing-page__status billing-page__status--success"
          role="status"
          data-testid="billing-checkout-success"
        >
          <strong>
            {confirmedPlanLabel
              ? t("checkout.success.titleWithPlan", { plan: confirmedPlanLabel })
              : t("checkout.success.title")}
          </strong>
          <p>
            {loadingConfirmation && !confirmedPlanLabel
              ? t("checkout.success.pendingBody")
              : t("checkout.success.body")}
          </p>
        </div>
      )}
      {checkoutStatus === "cancel" && (
        <div
          className="billing-page__status billing-page__status--cancel"
          role="status"
          data-testid="billing-checkout-cancel"
        >
          <strong>{t("checkout.cancel.title")}</strong>
          <p>{t("checkout.cancel.body")}</p>
        </div>
      )}
      <CurrentSubscription />
      <UsageMeter />
      <PlansGrid />
    </div>
  );
}
