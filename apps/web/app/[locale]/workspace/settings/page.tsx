"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useLocale } from "next-intl";
import { Link, usePathname } from "@/i18n/navigation";

import { PageTransition } from "@/components/console/PageTransition";
import { GlassCard } from "@/components/console/glass";
import { apiGet, logout } from "@/lib/api";
import { useDeveloperMode } from "@/lib/developer-mode";

type UserMe = { id: string; email: string; display_name?: string };

export default function SettingsPage() {
  const t = useTranslations("console-settings");
  const locale = useLocale();
  const pathname = usePathname();
  const { isDeveloperMode, toggleDeveloperMode } = useDeveloperMode();

  const [user, setUser] = useState<UserMe | null>(null);
  const [deleteMsg, setDeleteMsg] = useState("");

  useEffect(() => {
    void apiGet<UserMe>("/api/v1/auth/me")
      .then((data) => setUser(data))
      .catch(() => {});
  }, []);

  const sectionTitle: React.CSSProperties = {
    fontSize: 14,
    fontWeight: 600,
    color: "var(--console-text-primary, var(--text-primary))",
    marginBottom: 4,
  };

  const sectionDesc: React.CSSProperties = {
    fontSize: 12,
    color: "var(--console-text-secondary, var(--text-secondary))",
    lineHeight: 1.5,
  };

  const label: React.CSSProperties = {
    fontSize: 12,
    fontWeight: 500,
    color: "var(--console-text-secondary, var(--text-secondary))",
    marginBottom: 2,
  };

  const value: React.CSSProperties = {
    fontSize: 13,
    color: "var(--console-text-primary, var(--text-primary))",
  };

  return (
    <PageTransition>
      <div className="console-page-shell" style={{ padding: "28px 32px" }}>
        <div style={{ maxWidth: 640, margin: "0 auto" }}>
          {/* Page Header */}
          <div style={{ marginBottom: 28 }}>
            <p style={{
              fontSize: 11,
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              color: "var(--console-accent, var(--accent))",
              marginBottom: 6,
            }}>{t("kicker")}</p>
            <h1 style={{
              fontSize: 22,
              fontWeight: 700,
              color: "var(--console-text-primary, var(--text-primary))",
              marginBottom: 4,
            }}>{t("title")}</h1>
            <p style={{
              fontSize: 13,
              color: "var(--console-text-secondary, var(--text-secondary))",
            }}>{t("description")}</p>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {/* Account */}
            <GlassCard>
              <div style={sectionTitle}>{t("settings.account")}</div>
              <div style={{ marginTop: 12 }}>
                <div style={label}>{t("settings.email")}</div>
                <div style={{ ...value, fontFamily: "var(--font-mono, monospace)" }}>
                  {user ? user.email : t("settings.loadingUser")}
                </div>
              </div>
              {user?.display_name && (
                <div style={{ marginTop: 10 }}>
                  <div style={label}>{t("settings.name")}</div>
                  <div style={value}>{user.display_name}</div>
                </div>
              )}
            </GlassCard>

            {/* Language */}
            <GlassCard>
              <div style={sectionTitle}>{t("settings.language")}</div>
              <p style={{ ...sectionDesc, marginBottom: 14 }}>{t("settings.languageDesc")}</p>
              <div style={{ display: "flex", gap: 0, borderRadius: 9999, overflow: "hidden", border: "1px solid var(--console-border, var(--border))", width: "fit-content" }}>
                <Link
                  href={pathname}
                  locale="en"
                  style={{
                    padding: "6px 18px",
                    fontSize: 13,
                    fontWeight: 500,
                    textDecoration: "none",
                    transition: "all 0.15s ease",
                    ...(locale === "en"
                      ? {
                          background: "linear-gradient(135deg, var(--console-accent, var(--accent)), color-mix(in srgb, var(--console-accent, var(--accent)) 80%, white))",
                          color: "#fff",
                        }
                      : {
                          background: "transparent",
                          color: "var(--console-text-secondary, var(--text-secondary))",
                        }),
                  }}
                >
                  English
                </Link>
                <Link
                  href={pathname}
                  locale="zh"
                  style={{
                    padding: "6px 18px",
                    fontSize: 13,
                    fontWeight: 500,
                    textDecoration: "none",
                    transition: "all 0.15s ease",
                    ...(locale === "zh"
                      ? {
                          background: "linear-gradient(135deg, var(--console-accent, var(--accent)), color-mix(in srgb, var(--console-accent, var(--accent)) 80%, white))",
                          color: "#fff",
                        }
                      : {
                          background: "transparent",
                          color: "var(--console-text-secondary, var(--text-secondary))",
                        }),
                  }}
                >
                  中文
                </Link>
              </div>
            </GlassCard>

            {/* Developer Mode */}
            <GlassCard>
              <div style={sectionTitle}>{t("settings.developerMode")}</div>
              <p style={{ ...sectionDesc, marginBottom: 14 }}>{t("settings.developerModeDesc")}</p>
              <label style={{ display: "flex", alignItems: "center", gap: 12, cursor: "pointer", userSelect: "none" }}>
                <button
                  role="switch"
                  aria-checked={isDeveloperMode}
                  onClick={toggleDeveloperMode}
                  style={{
                    position: "relative",
                    display: "inline-flex",
                    height: 24,
                    width: 44,
                    flexShrink: 0,
                    borderRadius: 9999,
                    border: "none",
                    cursor: "pointer",
                    transition: "background 0.2s ease",
                    background: isDeveloperMode
                      ? "var(--console-accent, var(--warning))"
                      : "var(--console-border, var(--border))",
                    padding: 0,
                  }}
                >
                  <span
                    style={{
                      display: "inline-block",
                      height: 20,
                      width: 20,
                      borderRadius: 9999,
                      background: "white",
                      boxShadow: "0 1px 3px rgba(0,0,0,0.15)",
                      transform: isDeveloperMode ? "translateX(22px)" : "translateX(2px)",
                      transition: "transform 0.2s ease",
                      marginTop: 2,
                    }}
                  />
                </button>
                <span style={{ fontSize: 13, color: "var(--console-text-primary, var(--text-primary))" }}>
                  {isDeveloperMode ? t("settings.developerModeOn") : t("settings.developerModeOff")}
                </span>
              </label>
            </GlassCard>

            {/* Subscription */}
            <GlassCard>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
                <div style={sectionTitle}>{t("settings.subscription")}</div>
                <span style={{
                  display: "inline-flex",
                  alignItems: "center",
                  padding: "3px 10px",
                  borderRadius: 9999,
                  fontSize: 11,
                  fontWeight: 600,
                  background: "linear-gradient(135deg, var(--console-accent, var(--accent)), color-mix(in srgb, var(--console-accent, var(--accent)) 80%, white))",
                  color: "#fff",
                }}>
                  {t("settings.freePlan")}
                </span>
              </div>
              <p style={{ ...sectionDesc, marginBottom: 14 }}>{t("settings.subscriptionDesc")}</p>
              <div style={{
                fontSize: 11,
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                color: "var(--console-text-secondary, var(--text-secondary))",
                marginBottom: 8,
              }}>{t("settings.quotasKicker")}</div>
              <ul style={{
                margin: 0,
                paddingLeft: 16,
                fontSize: 13,
                lineHeight: 1.8,
                color: "var(--console-text-primary, var(--text-primary))",
                listStyleType: "disc",
              }}>
                <li>{t("settings.quota1")}</li>
                <li>{t("settings.quota2")}</li>
                <li>{t("settings.quota3")}</li>
              </ul>
            </GlassCard>

            {/* Danger Zone */}
            <div
              style={{
                background: "rgba(239,68,68,0.04)",
                backdropFilter: "blur(20px)",
                WebkitBackdropFilter: "blur(20px)",
                border: "1px solid rgba(239,68,68,0.15)",
                borderRadius: "var(--console-radius-lg, 16px)",
                padding: 20,
              }}
            >
              <div style={{ ...sectionTitle, color: "rgb(220,60,60)" }}>{t("settings.dangerZone")}</div>
              <p style={{ ...sectionDesc, marginBottom: 16 }}>{t("settings.dangerZoneDesc")}</p>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <button
                  onClick={() => void logout()}
                  style={{
                    padding: "7px 18px",
                    fontSize: 13,
                    fontWeight: 500,
                    borderRadius: 9999,
                    border: "1px solid var(--console-border, var(--border))",
                    background: "var(--console-surface, rgba(255,255,255,0.06))",
                    color: "var(--console-text-primary, var(--text-primary))",
                    cursor: "pointer",
                    transition: "all 0.15s ease",
                  }}
                >
                  {t("settings.logout")}
                </button>
                <button
                  onClick={() => setDeleteMsg(t("settings.deleteConfirm"))}
                  style={{
                    padding: "7px 18px",
                    fontSize: 13,
                    fontWeight: 500,
                    borderRadius: 9999,
                    border: "1px solid rgba(239,68,68,0.3)",
                    background: "rgba(239,68,68,0.08)",
                    color: "rgb(220,60,60)",
                    cursor: "pointer",
                    transition: "all 0.15s ease",
                  }}
                >
                  {t("settings.deleteData")}
                </button>
              </div>
              {deleteMsg ? (
                <div style={{
                  marginTop: 14,
                  padding: "8px 14px",
                  borderRadius: 10,
                  fontSize: 13,
                  background: "rgba(239,68,68,0.08)",
                  color: "rgb(220,60,60)",
                  border: "1px solid rgba(239,68,68,0.15)",
                }}>{deleteMsg}</div>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </PageTransition>
  );
}
