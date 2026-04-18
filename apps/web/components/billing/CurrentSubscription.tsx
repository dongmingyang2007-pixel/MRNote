"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { apiGet, apiPost } from "@/lib/api";

interface Me {
  plan: string;
  status: string;
  billing_cycle: string;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  provider: string;
}

export default function CurrentSubscription() {
  const t = useTranslations("billing");
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    void apiGet<Me>("/api/v1/billing/me")
      .then(setMe)
      .catch(() => setMe(null));
  }, []);

  const handleManage = async () => {
    try {
      const r = await apiPost<{ portal_url: string }>(
        "/api/v1/billing/portal", {},
      );
      window.location.href = r.portal_url;
    } catch (e) {
      console.error("portal failed", e);
    }
  };

  if (!me) return null;
  return (
    <section className="current-sub" data-testid="current-subscription">
      <div>
        {t("current.planLabel", {
          plan: me.plan.toUpperCase(),
          cycle: me.billing_cycle,
          status: me.status,
        })}
      </div>
      {me.current_period_end && (
        <div className="current-sub__renewal">
          {t("current.renewalLabel", { date: me.current_period_end.slice(0, 10) })}
          {me.cancel_at_period_end && ` ${t("current.cancelsLabel")}`}
        </div>
      )}
      {me.provider !== "free" && (
        <button
          type="button"
          onClick={handleManage}
          className="current-sub__manage"
          data-testid="current-sub-manage"
        >
          {t("current.manage")}
        </button>
      )}
    </section>
  );
}
