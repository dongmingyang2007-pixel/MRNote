/**
 * Billing SDK
 *
 * Typed wrappers around `/api/v1/billing/*` endpoints (Stripe checkout, portal,
 * `me` summary). Spec §23 mandates this module.
 */

import { apiGet, apiPost } from "@/lib/api";

export type PlanId = "free" | "pro" | "power" | "team";
export type BillingCycle = "monthly" | "yearly";

export interface Entitlement {
  [key: string]: number | boolean;
}

export interface BillingMeResponse {
  plan: string;
  status: string;
  billing_cycle: string;
  current_period_end: string | null;
  seats: number;
  cancel_at_period_end: boolean;
  provider: string;
  entitlements: Entitlement;
  usage_this_month: Record<string, number>;
}

export interface CheckoutStartInput {
  plan: PlanId;
  cycle: BillingCycle;
}

export interface CheckoutStartResponse {
  checkout_url: string;
}

export interface PortalResponse {
  url: string;
}

export interface PlanDescriptor {
  id: PlanId;
  name: string;
  monthlyPrice: number | null;
  yearlyPrice: number | null;
  features: string[];
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

export function getMe(): Promise<BillingMeResponse> {
  return apiGet<BillingMeResponse>("/api/v1/billing/me");
}

export function startCheckout(input: CheckoutStartInput): Promise<CheckoutStartResponse> {
  return apiPost<CheckoutStartResponse>("/api/v1/billing/checkout", input);
}

export function openPortal(): Promise<PortalResponse> {
  return apiPost<PortalResponse>("/api/v1/billing/portal", {});
}

// ---------------------------------------------------------------------------
// Grouped export
// ---------------------------------------------------------------------------

export const billingSDK = {
  getMe,
  startCheckout,
  openPortal,
} as const;

export default billingSDK;
