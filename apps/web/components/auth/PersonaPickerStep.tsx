"use client";

import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";
import { BookOpen, Network, Sparkles } from "lucide-react";

import { apiPatch, isApiRequestError } from "@/lib/api";
import { writeCookie } from "@/lib/cookie";
import { PERSONA_COOKIE_NAME } from "@/hooks/useRoleSelection";
import { type PersonaKey } from "@/lib/persona";

const THIRTY_DAYS_SECONDS = 60 * 60 * 24 * 30;

interface PersonaPickerStepProps {
  /** Called after the picker is resolved (either a persona was persisted
   *  server-side, or the user chose skip). Parent handles the navigation
   *  so the same component can be reused from settings in the future. */
  onResolved: (persona: PersonaKey | null) => void;
  locale: "zh" | "en";
}

interface PersonaOption {
  key: PersonaKey;
  titleKey: string;
  descriptionKey: string;
  Icon: typeof BookOpen;
}

// Icons chosen to mirror marketing HeroPersonaCopy:
//   student    → BookOpen  (textbooks / study)
//   researcher → Network   (memory graph)
//   pm         → Sparkles  (multi-thread / AI assist)
const OPTIONS: readonly PersonaOption[] = [
  { key: "student", titleKey: "register.persona.student.title", descriptionKey: "register.persona.student.description", Icon: BookOpen },
  { key: "researcher", titleKey: "register.persona.researcher.title", descriptionKey: "register.persona.researcher.description", Icon: Network },
  { key: "pm", titleKey: "register.persona.pm.title", descriptionKey: "register.persona.pm.description", Icon: Sparkles },
] as const;

/**
 * Step 2 of the register flow (post email+code). Per spec §1.1 / §1.2, we
 * collect a coarse `persona` so the homepage + digest can speak the user's
 * language on first login. The field is optional — "Skip for now" lands the
 * user in the console with `persona = null` and a settings nudge later.
 *
 * Persistence mirrors `useRoleSelection.setPersona`:
 *   1. PATCH /api/v1/auth/me { persona }
 *   2. Write the `mrai_persona` cookie as the local cache (30d TTL).
 *
 * The component is self-contained (no context / hook) so it can be dropped
 * into the register flow without threading RoleProvider into the auth tree.
 */
export default function PersonaPickerStep({ onResolved, locale }: PersonaPickerStepProps) {
  const t = useTranslations("auth");
  const [selected, setSelected] = useState<PersonaKey | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const persist = useCallback(
    async (value: PersonaKey | null) => {
      setSubmitting(true);
      setError("");
      try {
        // PATCH is the source of truth. If this fails we surface the error
        // rather than silently dropping into the console with a stale value.
        await apiPatch<unknown>("/api/v1/auth/me", { persona: value });
        if (value) {
          writeCookie(PERSONA_COOKIE_NAME, value, THIRTY_DAYS_SECONDS);
        }
        onResolved(value);
      } catch (err) {
        // Don't block progress on persona save — the user can set it in
        // settings. But tell them what happened so they know the homepage
        // may look generic the first time around.
        const fallback = t("register.persona.error");
        setError(
          isApiRequestError(err) && err.message ? err.message : fallback,
        );
        setSubmitting(false);
      }
    },
    [onResolved, t],
  );

  const handleContinue = useCallback(() => {
    if (submitting) return;
    void persist(selected);
  }, [persist, selected, submitting]);

  const handleSkip = useCallback(() => {
    if (submitting) return;
    void persist(null);
  }, [persist, submitting]);

  return (
    <section
      className="flex w-full flex-col text-left"
      aria-label={t("register.persona.heading")}
    >
      <div>
        <h1 className="font-display text-[22px] font-semibold tracking-[-0.01em] text-[var(--text-primary)]">
          {t("register.persona.heading")}
        </h1>
        <p className="mt-2 text-[13px] leading-relaxed text-[var(--text-secondary)]">
          {t("register.persona.subheading")}
        </p>
      </div>

      <div
        role="radiogroup"
        aria-label={t("register.persona.heading")}
        className="mt-6 flex flex-col gap-3"
      >
        {OPTIONS.map(({ key, titleKey, descriptionKey, Icon }) => {
          const active = selected === key;
          return (
            <button
              key={key}
              type="button"
              role="radio"
              aria-checked={active}
              disabled={submitting}
              onClick={() => setSelected(key)}
              className={[
                "group relative flex w-full cursor-pointer items-start gap-3 rounded-[var(--radius-md)] border px-4 py-4 text-left transition-all duration-[var(--motion-base)]",
                active
                  ? "border-[var(--brand-v2)] bg-[var(--brand-soft)] shadow-sm"
                  : "border-[var(--border)] bg-[var(--bg-base)] hover:border-[var(--brand-v2)]/40 hover:bg-[var(--bg-surface)]",
                submitting ? "cursor-not-allowed opacity-60" : "",
              ].join(" ")}
            >
              <span
                className={[
                  "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-colors",
                  active
                    ? "bg-[var(--brand-v2)] text-white"
                    : "bg-[var(--bg-surface)] text-[var(--text-secondary)] group-hover:text-[var(--brand-v2)]",
                ].join(" ")}
                aria-hidden="true"
              >
                <Icon size={16} strokeWidth={1.8} />
              </span>
              <span className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="text-sm font-semibold text-[var(--text-primary)]">
                  {t(titleKey)}
                </span>
                <span className="text-[12px] leading-relaxed text-[var(--text-secondary)]">
                  {t(descriptionKey)}
                </span>
              </span>
              <span
                className={[
                  "mt-1 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border transition-colors",
                  active
                    ? "border-[var(--brand-v2)] bg-[var(--brand-v2)]"
                    : "border-[var(--border)] bg-transparent",
                ].join(" ")}
                aria-hidden="true"
              >
                {active && (
                  <svg
                    className="h-2.5 w-2.5 text-white"
                    viewBox="0 0 10 10"
                    fill="none"
                  >
                    <path
                      d="M2 5.2 4.2 7.4 8 3.6"
                      stroke="currentColor"
                      strokeWidth="1.6"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                )}
              </span>
            </button>
          );
        })}
      </div>

      <div className="mt-6 flex flex-col gap-3">
        <button
          type="button"
          onClick={handleContinue}
          disabled={submitting || !selected}
          className="w-full cursor-pointer rounded-[var(--radius-full)] bg-[var(--brand-v2)] py-3 text-sm font-semibold text-white transition-opacity duration-[var(--motion-base)] hover:opacity-90 active:opacity-80 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? (
            <span className="inline-flex items-center justify-center gap-2">
              <svg
                className="h-4 w-4 animate-spin"
                viewBox="0 0 24 24"
                fill="none"
                aria-hidden="true"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                />
              </svg>
              {t("register.persona.continue")}
            </span>
          ) : (
            t("register.persona.continue")
          )}
        </button>
        <button
          type="button"
          onClick={handleSkip}
          disabled={submitting}
          className="w-full cursor-pointer rounded-[var(--radius-full)] border border-transparent py-2 text-sm font-medium text-[var(--text-secondary)] transition-colors hover:text-[var(--text-primary)] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {t("register.persona.skip")}
        </button>
      </div>

      <div
        role="alert"
        aria-live="polite"
        className={`mt-4 flex items-start gap-2 rounded-[var(--radius-md)] border px-4 py-3 text-sm transition-all duration-200 ${
          error
            ? "border-red-200 bg-red-50 text-red-700 opacity-100"
            : "pointer-events-none h-0 overflow-hidden border-transparent p-0 opacity-0"
        }`}
      >
        {error && (
          <>
            <svg
              className="mt-0.5 h-4 w-4 shrink-0"
              viewBox="0 0 20 20"
              fill="currentColor"
              aria-hidden="true"
            >
              <path
                fillRule="evenodd"
                d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
                clipRule="evenodd"
              />
              <title>{locale === "zh" ? "错误" : "Error"}</title>
            </svg>
            <span>{error}</span>
          </>
        )}
      </div>
    </section>
  );
}
