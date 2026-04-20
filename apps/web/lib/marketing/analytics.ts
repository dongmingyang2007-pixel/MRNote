export type LandingEvent =
  | "landing.role.selected"
  | "landing.role.switched"
  | "landing.role.cleared"
  | "landing.role.restored"
  | "landing.offer.clicked";

export function emitLandingEvent(
  event: LandingEvent,
  payload: Record<string, string | number | null | undefined>,
): void {
  if (process.env.NODE_ENV !== "production") {
    // eslint-disable-next-line no-console
    console.debug("[mrai.analytics]", event, payload);
    return;
  }
  // TODO: wire to real analytics provider (Plausible / PostHog / Amplitude).
}
