"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

export interface BillingMe {
  plan: string;
  status: string;
  billing_cycle: string;
  current_period_end: string | null;
  seats: number;
  cancel_at_period_end: boolean;
  provider: string;
  entitlements: Record<string, number | boolean>;
  usage_this_month: Record<string, number>;
}

export function useBillingMe(): BillingMe | null {
  const [me, setMe] = useState<BillingMe | null>(null);
  useEffect(() => {
    void apiGet<BillingMe>("/api/v1/billing/me")
      .then(setMe)
      .catch(() => setMe(null));
  }, []);
  return me;
}
