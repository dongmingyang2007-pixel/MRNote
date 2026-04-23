/**
 * `Persona` is the server-side user-identity field (users.persona). It is a
 * narrower three-value vocabulary than the landing `RoleKey`: the homepage
 * role picker lets a visitor preview any of six roles, but the account
 * setting stores just one coarse identity so the backend can route
 * notifications / offers without encoding marketing micro-segments.
 *
 * This module is intentionally UI-free so it can be imported from both
 * server components and client hooks.
 */

export type PersonaKey = "student" | "researcher" | "pm";

export const PERSONA_KEYS: readonly PersonaKey[] = [
  "student",
  "researcher",
  "pm",
] as const;

export function isPersonaKey(value: unknown): value is PersonaKey {
  return (
    typeof value === "string" &&
    (PERSONA_KEYS as readonly string[]).includes(value)
  );
}
