"use client";

import "@/styles/billing.css";
import CurrentSubscription from "@/components/billing/CurrentSubscription";
import UsageMeter from "@/components/billing/UsageMeter";
import PlansGrid from "@/components/billing/PlansGrid";

export default function BillingSettingsPage() {
  return (
    <div className="billing-page" data-testid="billing-page">
      <h1 className="billing-page__title">Billing</h1>
      <CurrentSubscription />
      <UsageMeter />
      <PlansGrid />
    </div>
  );
}
