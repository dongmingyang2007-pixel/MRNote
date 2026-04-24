"use client";

import { Link } from "@/i18n/navigation";
import { useRef, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { gsap } from "@/lib/gsap-register";

import { apiPost, persistWorkspaceId } from "@/lib/api";
import { getLocalizedAuthError } from "@/lib/auth-errors";
import { getSafeNavigationPath } from "@/lib/security";
import GoogleSignInButton from "@/components/auth/GoogleSignInButton";

function getDefaultConsolePath(): string {
  if (typeof window !== "undefined" && window.location.pathname.startsWith("/en/")) {
    return "/en/app";
  }
  return "/app";
}

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const sectionRef = useRef<HTMLElement>(null);
  const t = useTranslations("auth");

  useEffect(() => {
    const el = sectionRef.current;
    if (!el) return;
    const ctx = gsap.context(() => {
      const tl = gsap.timeline({ defaults: { ease: "power2.out" } });
      tl.from(".auth-heading", { opacity: 0, y: 20, duration: 0.6 });
      tl.from(".auth-form-card", { opacity: 0, y: 30, duration: 0.6 }, "<0.15");
    }, el);
    return () => ctx.revert();
  }, []);

  const inputClass = "w-full rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-base)] px-4 py-3 text-[var(--text-primary)] placeholder:text-[var(--text-secondary)] transition-colors duration-[var(--motion-base)] focus:border-[var(--brand-v2)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-v2)]/30 focus-visible:ring-offset-1";

  return (
    <section ref={sectionRef} className="flex w-full flex-col text-left">
      <div className="auth-heading">
        <h1 className="font-display text-[22px] font-semibold tracking-[-0.01em] text-[var(--text-primary)]">
          {t("login.heading")}
        </h1>
      </div>

      <div className="auth-form-card mt-6 w-full">
        <div className="auth-oauth-block">
          <GoogleSignInButton />
          <div className="auth-divider">
            <span>{t("oauth.divider")}</span>
          </div>
        </div>

        <form
          className="space-y-4"
          onSubmit={async (e) => {
            e.preventDefault();
            setError("");
            setLoading(true);
            try {
              const auth = await apiPost<{ workspace: { id: string }; access_token_expires_in_seconds: number }>(
                "/api/v1/auth/login",
                { email, password },
              );
              persistWorkspaceId(auth.workspace.id, auth.access_token_expires_in_seconds);
              const nextPath = getSafeNavigationPath(
                new URLSearchParams(window.location.search).get("next"),
              );
              window.location.replace(nextPath || getDefaultConsolePath());
            } catch (err) {
              setError(getLocalizedAuthError(err, t, "login.error"));
            } finally {
              setLoading(false);
            }
          }}
        >
          <div>
            <label className="mb-2 block text-sm font-medium text-[var(--text-secondary)]" htmlFor="login-email">
              {t("login.email.label")}
            </label>
            <input
              id="login-email"
              type="email"
              required
              className={inputClass}
              placeholder={t("login.email.placeholder")}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div>
            <label className="mb-2 block text-sm font-medium text-[var(--text-secondary)]" htmlFor="login-password">
              {t("login.password.label")}
            </label>
            <div className="relative">
              <input
                id="login-password"
                type={showPassword ? "text" : "password"}
                required
                className={`${inputClass} pr-11`}
                placeholder={t("login.password.placeholder")}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <button
                type="button"
                className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center justify-center w-10 h-10 rounded-md text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-black/5 transition-colors cursor-pointer"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? (
                  <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5">
                    <path d="M3.98 8.223A10.477 10.477 0 0 0 1.934 12c1.292 4.338 5.31 7.5 10.066 7.5.993 0 1.953-.138 2.863-.395M6.228 6.228A10.451 10.451 0 0 1 12 4.5c4.756 0 8.773 3.162 10.065 7.498a10.522 10.522 0 0 1-4.293 5.774M6.228 6.228 3 3m3.228 3.228 3.65 3.65m7.894 7.894L21 21m-3.228-3.228-3.65-3.65m0 0a3 3 0 1 0-4.243-4.243m4.242 4.242L9.88 9.88" />
                  </svg>
                ) : (
                  <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5">
                    <path d="M2.036 12.322a1.012 1.012 0 0 1 0-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178Z" />
                    <path d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
                  </svg>
                )}
              </button>
            </div>
          </div>
          <button
            type="submit"
            disabled={loading}
            className="w-full cursor-pointer rounded-[var(--radius-full)] bg-[var(--brand-v2)] py-3 text-sm font-semibold text-white transition-opacity duration-[var(--motion-base)] hover:opacity-90 active:opacity-80 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loading ? (
              <span className="inline-flex items-center gap-2">
                <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" /></svg>
                {t("login.submit")}
              </span>
            ) : t("login.submit")}
          </button>
          <div
            role="alert"
            aria-live="polite"
            className={`flex items-start gap-2 rounded-[var(--radius-md)] border px-4 py-3 text-sm transition-all duration-200 ${error ? "border-red-200 bg-red-50 text-red-700 opacity-100" : "pointer-events-none h-0 overflow-hidden border-transparent p-0 opacity-0"}`}
          >
            {error && (
              <>
                <svg className="mt-0.5 h-4 w-4 shrink-0" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" /></svg>
                <span>{error}</span>
              </>
            )}
          </div>
        </form>

        <div className="mt-6 space-y-2 text-center text-sm text-[var(--text-secondary)]">
          <div>
            <Link href="/forgot-password" className="font-medium text-[var(--brand-v2)] underline-offset-4 hover:underline">
              {t("login.forgotPassword")}
            </Link>
          </div>
          <div>
            {t("login.noAccount")}{" "}
            <Link href="/register" className="font-medium text-[var(--brand-v2)] underline-offset-4 hover:underline">
              {t("login.register")}
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
