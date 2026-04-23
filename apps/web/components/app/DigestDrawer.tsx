"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Sun, X } from "lucide-react";

import {
  fetchDailyDigest,
  markDailyRead,
  todayISO,
  type ServerDailyDigest,
} from "@/lib/digest-sdk";

const DISMISSED_KEY_PREFIX = "mrai.digest.read.";
const READ_MARK = "1";

/** Minimum-viable in-app morning digest. On first load of the workspace,
 *  fetch today's digest; if we got one and the user hasn't already dismissed
 *  today's card (localStorage sentinel), slide it in from the top. Closing
 *  and "稍后再看" both post mark-read + set localStorage so it stays dismissed.
 *
 *  This component is intentionally lightweight: no animation library, no
 *  design-token rewiring — just inline styles that land next to the
 *  GlassTopBar without fighting it. */
export default function DigestDrawer() {
  const t = useTranslations("console.digestDrawer");

  const [digest, setDigest] = useState<ServerDailyDigest | null>(null);
  const [visible, setVisible] = useState(false);
  const [dismissing, setDismissing] = useState(false);

  useEffect(() => {
    const today = todayISO();
    const key = DISMISSED_KEY_PREFIX + today;

    // Short-circuit if already dismissed today. Avoids even fetching.
    if (typeof window !== "undefined" && window.localStorage.getItem(key) === READ_MARK) {
      return;
    }

    let cancelled = false;
    void (async () => {
      const d = await fetchDailyDigest(today);
      if (cancelled || !d) return;
      setDigest(d);
      // Small rAF so the entrance transition can animate from offscreen.
      requestAnimationFrame(() => {
        if (!cancelled) setVisible(true);
      });
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const dismiss = useCallback(
    async (mode: "later" | "start") => {
      if (dismissing) return;
      setDismissing(true);

      const today = todayISO();
      try {
        window.localStorage.setItem(DISMISSED_KEY_PREFIX + today, READ_MARK);
      } catch {
        /* Storage may be blocked in privacy modes — don't let that break the flow. */
      }

      // "Later" (dismiss X or 稍后再看) both mark the digest as read server-side.
      // "Start today" is a softer acknowledgment — still flip the read flag so
      // the same card doesn't re-bump next navigation, but we don't open any
      // sub-flow here (that's a future page-creation spec).
      if (mode === "later" || mode === "start") {
        void markDailyRead(today);
      }

      setVisible(false);
      // Let the slide-out finish before unmounting the digest data.
      window.setTimeout(() => {
        setDigest(null);
        setDismissing(false);
      }, 260);
    },
    [dismissing],
  );

  if (!digest) return null;

  return (
    <div
      aria-live="polite"
      style={{
        position: "fixed",
        top: 0,
        left: "50%",
        transform: `translate(-50%, ${visible ? "12px" : "calc(-100% - 20px)"})`,
        transition: "transform 260ms cubic-bezier(0.22, 1, 0.36, 1)",
        zIndex: 60,
        width: "min(720px, calc(100vw - 32px))",
        pointerEvents: visible ? "auto" : "none",
      }}
    >
      <article
        style={{
          background: "var(--console-surface, rgba(255,255,255,0.92))",
          backdropFilter: "blur(20px)",
          WebkitBackdropFilter: "blur(20px)",
          border: "1px solid var(--console-border, var(--border))",
          borderRadius: "var(--console-radius-lg, 16px)",
          boxShadow: "var(--console-shadow-card, 0 18px 48px -24px rgba(0,0,0,0.25))",
          padding: "14px 16px",
          display: "flex",
          flexDirection: "column",
          gap: 10,
        }}
      >
        <header style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              width: 22,
              height: 22,
              borderRadius: 9999,
              background: "color-mix(in srgb, var(--console-accent, var(--accent)) 14%, transparent)",
              color: "var(--console-accent, var(--accent))",
            }}
          >
            <Sun size={13} aria-hidden="true" />
          </span>
          <span style={{ fontSize: 12, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--console-text-secondary, var(--text-secondary))" }}>
            {t("greeting")}
          </span>
          <span style={{ fontSize: 12, color: "var(--console-text-secondary, var(--text-secondary))" }}>
            {digest.date}
          </span>
          <span style={{ flex: 1 }} aria-hidden="true" />
          <button
            type="button"
            onClick={() => void dismiss("later")}
            aria-label={t("dismiss")}
            style={{
              width: 24,
              height: 24,
              borderRadius: 9999,
              border: "none",
              background: "transparent",
              color: "var(--console-text-secondary, var(--text-secondary))",
              cursor: "pointer",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <X size={14} aria-hidden="true" />
          </button>
        </header>

        <p style={{ margin: 0, fontSize: 14, lineHeight: 1.55, color: "var(--console-text-primary, var(--text-primary))" }}>
          {digest.greeting}
        </p>

        {/* Compact block list — only shows the first 2 blocks' items so the
            drawer doesn't crowd the top of the viewport. Full digest lives
            on the homepage / dedicated digest page. */}
        <ul
          style={{
            margin: 0,
            padding: 0,
            listStyle: "none",
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          {digest.blocks.slice(0, 2).flatMap((block) => {
            if (block.kind === "insight") {
              return [
                <li
                  key={`insight-${block.title}`}
                  style={{
                    fontSize: 13,
                    lineHeight: 1.5,
                    color: "var(--console-text-primary, var(--text-primary))",
                    paddingLeft: 8,
                    borderLeft: "2px solid color-mix(in srgb, var(--console-accent, var(--accent)) 40%, transparent)",
                  }}
                >
                  <span style={{ fontWeight: 600 }}>{block.title}</span>
                  <span style={{ color: "var(--console-text-secondary, var(--text-secondary))" }}>
                    {" · "}
                    {block.body}
                  </span>
                </li>,
              ];
            }
            return block.items.slice(0, 2).map((item, i) => (
              <li
                key={`${block.kind}-${i}-${item.label.slice(0, 10)}`}
                style={{
                  fontSize: 13,
                  lineHeight: 1.5,
                  display: "flex",
                  gap: 8,
                  color: "var(--console-text-primary, var(--text-primary))",
                }}
              >
                <span
                  style={{
                    flexShrink: 0,
                    width: 4,
                    height: 4,
                    marginTop: 8,
                    borderRadius: 9999,
                    background:
                      block.kind === "today"
                        ? "var(--console-accent, var(--accent))"
                        : "var(--console-text-secondary, var(--text-secondary))",
                  }}
                />
                <span>
                  {item.label}
                  <span style={{ color: "var(--console-text-secondary, var(--text-secondary))" }}>
                    {" · "}
                    {item.tag}
                  </span>
                </span>
              </li>
            ));
          })}
        </ul>

        <footer style={{ display: "flex", gap: 8, justifyContent: "flex-end", flexWrap: "wrap" }}>
          <button
            type="button"
            onClick={() => void dismiss("later")}
            disabled={dismissing}
            style={{
              padding: "6px 14px",
              fontSize: 12,
              fontWeight: 500,
              borderRadius: 9999,
              border: "1px solid var(--console-border, var(--border))",
              background: "transparent",
              color: "var(--console-text-secondary, var(--text-secondary))",
              cursor: dismissing ? "default" : "pointer",
            }}
          >
            {t("dismiss")}
          </button>
          <button
            type="button"
            onClick={() => void dismiss("start")}
            disabled={dismissing}
            style={{
              padding: "6px 16px",
              fontSize: 12,
              fontWeight: 600,
              borderRadius: 9999,
              border: "1px solid transparent",
              background:
                "linear-gradient(135deg, var(--console-accent, var(--accent)), color-mix(in srgb, var(--console-accent, var(--accent)) 80%, white))",
              color: "#fff",
              cursor: dismissing ? "default" : "pointer",
            }}
          >
            {t("ctaStartToday")}
          </button>
        </footer>
      </article>
    </div>
  );
}
