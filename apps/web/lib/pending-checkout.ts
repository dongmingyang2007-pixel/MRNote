import type { BillingCycle, PlanId } from "@/lib/billing-sdk";

export interface PendingCheckoutPlan {
  plan: PlanId;
  cycle: BillingCycle;
}

export type PaidPlanId = Exclude<PlanId, "free">;

export const PENDING_CHECKOUT_PLAN_STORAGE_KEY = "mrnote.pendingCheckoutPlan";

type SearchParamsLike = Pick<URLSearchParams, "get">;

const PLAN_IDS = new Set<PlanId>(["free", "pro", "power", "team"]);
const PAID_PLAN_IDS = new Set<PaidPlanId>(["pro", "power", "team"]);
const BILLING_CYCLES = new Set<BillingCycle>(["monthly", "yearly"]);

function normalizePlan(value: string | null): PlanId | null {
  if (!value || !PLAN_IDS.has(value as PlanId)) {
    return null;
  }
  return value as PlanId;
}

function normalizeCycle(value: string | null): BillingCycle {
  if (value && BILLING_CYCLES.has(value as BillingCycle)) {
    return value as BillingCycle;
  }
  return "monthly";
}

function getSessionStorage(): Storage | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function parsePendingCheckoutPlan(
  searchParams: SearchParamsLike | null | undefined,
): PendingCheckoutPlan | null {
  const plan = normalizePlan(searchParams?.get("plan") ?? null);
  if (!plan) {
    return null;
  }
  return {
    plan,
    cycle: normalizeCycle(searchParams?.get("cycle") ?? null),
  };
}

export function isPaidCheckoutPlan(
  value: PendingCheckoutPlan | null | undefined,
): value is PendingCheckoutPlan & { plan: PaidPlanId } {
  return Boolean(value && PAID_PLAN_IDS.has(value.plan as PaidPlanId));
}

export function isPaidPlanId(value: string | null | undefined): value is PaidPlanId {
  return Boolean(value && PAID_PLAN_IDS.has(value as PaidPlanId));
}

export function persistPendingCheckoutPlan(value: PendingCheckoutPlan): void {
  const storage = getSessionStorage();
  if (!storage) {
    return;
  }
  try {
    storage.setItem(PENDING_CHECKOUT_PLAN_STORAGE_KEY, JSON.stringify(value));
  } catch {
    // Storage is only a convenience across the Stripe redirect. The URL
    // driven flow remains authoritative if this write is unavailable.
  }
}

export function readStoredPendingCheckoutPlan(): PendingCheckoutPlan | null {
  const storage = getSessionStorage();
  if (!storage) {
    return null;
  }
  try {
    const raw = storage.getItem(PENDING_CHECKOUT_PLAN_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as Partial<PendingCheckoutPlan>;
    const plan = normalizePlan(typeof parsed.plan === "string" ? parsed.plan : null);
    if (!plan) {
      return null;
    }
    return {
      plan,
      cycle: normalizeCycle(typeof parsed.cycle === "string" ? parsed.cycle : null),
    };
  } catch {
    return null;
  }
}

export function clearPendingCheckoutPlan(): void {
  const storage = getSessionStorage();
  try {
    storage?.removeItem(PENDING_CHECKOUT_PLAN_STORAGE_KEY);
  } catch {
    // Ignore storage failures; clearing is best effort.
  }
}
