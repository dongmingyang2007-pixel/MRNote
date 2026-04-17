"use client";

import { useEffect, useState } from "react";
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
        <strong>Current plan:</strong> {me.plan.toUpperCase()}{" "}
        ({me.billing_cycle}) — {me.status}
      </div>
      {me.current_period_end && (
        <div className="current-sub__renewal">
          Renews: {me.current_period_end.slice(0, 10)}
          {me.cancel_at_period_end && " (cancels at period end)"}
        </div>
      )}
      {me.provider !== "free" && (
        <button
          type="button"
          onClick={handleManage}
          className="current-sub__manage"
          data-testid="current-sub-manage"
        >
          Manage billing
        </button>
      )}
    </section>
  );
}
