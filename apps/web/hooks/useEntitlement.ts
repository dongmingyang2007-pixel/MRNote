"use client";

import { useBillingMe } from "./useBillingMe";

export interface EntitlementState {
  loaded: boolean;
  allowed: boolean;
  current?: number;
  limit?: number;
}

export function useEntitlement(key: string): EntitlementState {
  const me = useBillingMe();
  if (!me) return { loaded: false, allowed: false };
  const value = me.entitlements[key];
  if (typeof value === "boolean") {
    return { loaded: true, allowed: value };
  }
  if (typeof value === "number") {
    if (value === -1) return { loaded: true, allowed: true, limit: -1 };
    const usageKey = key.replace(".max", "").replace(".monthly", "");
    const current = me.usage_this_month[usageKey] || 0;
    return { loaded: true, allowed: current < value, current, limit: value };
  }
  return { loaded: true, allowed: false };
}
