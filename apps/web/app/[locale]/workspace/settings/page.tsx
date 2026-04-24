"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Link, usePathname } from "@/i18n/navigation";
import {
  BadgeCheck,
  Code2,
  CreditCard,
  Globe2,
  LogOut,
  Mail,
  Shield,
  Trash2,
  User,
} from "lucide-react";

import { PageTransition } from "@/components/console/PageTransition";
import ConnectedAccountsList from "@/components/settings/ConnectedAccountsList";
import PersonaSection from "@/components/settings/PersonaSection";
import { apiGet, logout } from "@/lib/api";
import { useDeveloperMode } from "@/lib/developer-mode";

type UserMe = { id: string; email: string; display_name?: string };

const cardStyle: React.CSSProperties = {
  border: "1px solid var(--console-border-subtle, rgba(13, 148, 136, 0.14))",
  borderRadius: 22,
  background: "rgba(255, 255, 255, 0.82)",
  boxShadow: "var(--console-shadow-card, 0 14px 40px rgba(6, 43, 40, 0.08))",
  backdropFilter: "blur(20px)",
  WebkitBackdropFilter: "blur(20px)",
};

const mutedText: React.CSSProperties = {
  color: "var(--console-text-muted, #64748b)",
  lineHeight: 1.6,
};

function SettingsCard({
  icon,
  title,
  description,
  children,
  danger = false,
}: {
  icon: ReactNode;
  title: string;
  description?: string;
  children: ReactNode;
  danger?: boolean;
}) {
  return (
    <section
      style={{
        ...cardStyle,
        padding: 22,
        borderColor: danger
          ? "rgba(220, 38, 38, 0.18)"
          : "var(--console-border-subtle, rgba(13, 148, 136, 0.14))",
        background: danger ? "rgba(255, 247, 247, 0.82)" : cardStyle.background,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: 14,
          marginBottom: 18,
        }}
      >
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: 13,
            display: "grid",
            placeItems: "center",
            color: danger
              ? "rgb(220, 38, 38)"
              : "var(--console-accent, #0D9488)",
            background: danger
              ? "rgba(220, 38, 38, 0.08)"
              : "var(--console-accent-soft, rgba(13, 148, 136, 0.1))",
            flexShrink: 0,
          }}
        >
          {icon}
        </div>
        <div>
          <h2
            style={{
              margin: 0,
              fontSize: "1rem",
              fontWeight: 800,
              color: danger
                ? "rgb(153, 27, 27)"
                : "var(--console-text-primary, #0f172a)",
            }}
          >
            {title}
          </h2>
          {description ? (
            <p
              style={{ ...mutedText, margin: "6px 0 0", fontSize: "0.8125rem" }}
            >
              {description}
            </p>
          ) : null}
        </div>
      </div>
      {children}
    </section>
  );
}

function FieldRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(96px, 0.34fr) minmax(0, 1fr)",
        gap: 16,
        padding: "13px 0",
        borderTop:
          "1px solid var(--console-border-subtle, rgba(13, 148, 136, 0.12))",
      }}
    >
      <div style={{ fontSize: "0.75rem", fontWeight: 700, ...mutedText }}>
        {label}
      </div>
      <div
        style={{
          minWidth: 0,
          color: "var(--console-text-primary, #0f172a)",
          fontSize: "0.875rem",
          fontFamily: mono ? "var(--font-mono, monospace)" : undefined,
          overflowWrap: "anywhere",
        }}
      >
        {value}
      </div>
    </div>
  );
}

function GhostButton({
  children,
  danger = false,
  onClick,
}: {
  children: ReactNode;
  danger?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        minHeight: 38,
        padding: "8px 14px",
        borderRadius: 999,
        border: danger
          ? "1px solid rgba(220, 38, 38, 0.26)"
          : "1px solid var(--console-border-subtle, rgba(13, 148, 136, 0.14))",
        background: danger
          ? "rgba(220, 38, 38, 0.07)"
          : "rgba(255,255,255,0.76)",
        color: danger
          ? "rgb(185, 28, 28)"
          : "var(--console-text-primary, #0f172a)",
        fontSize: "0.8125rem",
        fontWeight: 800,
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}

export default function SettingsPage() {
  const t = useTranslations("console-settings");
  const tAuth = useTranslations("auth");
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

  return (
    <PageTransition>
      <div
        className="console-page-shell"
        style={{ padding: "clamp(18px, 3vw, 36px)" }}
      >
        <div style={{ maxWidth: 1180, margin: "0 auto" }}>
          <div
            style={{
              ...cardStyle,
              padding: "26px clamp(20px, 3vw, 32px)",
              marginBottom: 22,
              display: "grid",
              gridTemplateColumns: "minmax(0, 1fr) auto",
              gap: 22,
              alignItems: "end",
            }}
          >
            <div>
              <p
                style={{
                  margin: "0 0 8px",
                  fontSize: "0.75rem",
                  fontWeight: 800,
                  color: "var(--console-accent, #0D9488)",
                }}
              >
                {t("kicker")}
              </p>
              <h1
                style={{
                  margin: 0,
                  fontSize: "clamp(1.65rem, 3vw, 2.35rem)",
                  lineHeight: 1.05,
                  fontWeight: 900,
                  color: "var(--console-text-primary, #0f172a)",
                }}
              >
                {t("title")}
              </h1>
              <p
                style={{
                  ...mutedText,
                  margin: "12px 0 0",
                  maxWidth: 640,
                  fontSize: "0.9375rem",
                }}
              >
                {t("description")}
              </p>
            </div>
            <Link
              href="/app/settings/billing"
              data-testid="settings-manage-billing"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                minHeight: 42,
                padding: "9px 16px",
                borderRadius: 999,
                color: "#fff",
                background:
                  "var(--console-cta-gradient, linear-gradient(135deg, #F97316, #EA6A0F))",
                boxShadow: "0 12px 34px rgba(249, 115, 22, 0.22)",
                textDecoration: "none",
                fontSize: "0.875rem",
                fontWeight: 800,
                whiteSpace: "nowrap",
              }}
            >
              <CreditCard size={16} />
              {t("settings.manageBilling")}
            </Link>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(260px, 320px) minmax(0, 1fr)",
              gap: 22,
              alignItems: "start",
            }}
            className="settings-dashboard-grid"
          >
            <aside style={{ display: "grid", gap: 14 }}>
              <section style={{ ...cardStyle, padding: 22 }}>
                <div
                  style={{
                    width: 52,
                    height: 52,
                    borderRadius: 18,
                    display: "grid",
                    placeItems: "center",
                    color: "#fff",
                    background:
                      "linear-gradient(135deg, var(--console-accent, #0D9488), var(--console-accent-secondary, #14B8A6))",
                    boxShadow: "0 18px 38px rgba(13, 148, 136, 0.22)",
                    marginBottom: 14,
                  }}
                >
                  <User size={22} />
                </div>
                <h2
                  style={{
                    margin: 0,
                    fontSize: "1rem",
                    fontWeight: 900,
                    color: "var(--console-text-primary, #0f172a)",
                  }}
                >
                  {user?.display_name || t("settings.account")}
                </h2>
                <p
                  style={{
                    ...mutedText,
                    margin: "8px 0 0",
                    fontSize: "0.8125rem",
                    overflowWrap: "anywhere",
                  }}
                >
                  {user?.email || t("settings.loadingUser")}
                </p>
              </section>

              <section style={{ ...cardStyle, padding: 18 }}>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 12,
                  }}
                >
                  <div>
                    <div
                      style={{
                        fontSize: "0.75rem",
                        fontWeight: 800,
                        color: "var(--console-text-muted, #64748b)",
                      }}
                    >
                      {t("settings.subscription")}
                    </div>
                    <div
                      style={{
                        marginTop: 6,
                        fontSize: "1.35rem",
                        fontWeight: 900,
                        color: "var(--console-text-primary, #0f172a)",
                      }}
                    >
                      {t("settings.freePlan")}
                    </div>
                  </div>
                  <BadgeCheck
                    size={28}
                    color="var(--console-accent, #0D9488)"
                  />
                </div>
              </section>

              <section style={{ ...cardStyle, padding: 18 }}>
                <div
                  style={{ fontSize: "0.75rem", fontWeight: 800, ...mutedText }}
                >
                  {t("settings.quotasKicker")}
                </div>
                <ul
                  style={{
                    margin: "10px 0 0",
                    paddingLeft: 18,
                    fontSize: "0.8125rem",
                    lineHeight: 1.85,
                    color: "var(--console-text-primary, #0f172a)",
                  }}
                >
                  <li>{t("settings.quota1")}</li>
                  <li>{t("settings.quota2")}</li>
                  <li>{t("settings.quota3")}</li>
                </ul>
              </section>
            </aside>

            <div style={{ display: "grid", gap: 16 }}>
              <SettingsCard
                icon={<Mail size={18} />}
                title={t("settings.account")}
                description={t("settings.subscriptionDesc")}
              >
                <FieldRow
                  label={t("settings.email")}
                  value={user ? user.email : t("settings.loadingUser")}
                  mono
                />
                {user?.display_name ? (
                  <FieldRow
                    label={t("settings.name")}
                    value={user.display_name}
                  />
                ) : null}
              </SettingsCard>

              <SettingsCard
                icon={<Shield size={18} />}
                title={tAuth("connectedAccounts.title")}
                description={tAuth("connectedAccounts.desc")}
              >
                <ConnectedAccountsList />
              </SettingsCard>

              <PersonaSection />

              <SettingsCard
                icon={<Globe2 size={18} />}
                title={t("settings.language")}
                description={t("settings.languageDesc")}
              >
                <div
                  style={{
                    display: "inline-grid",
                    gridTemplateColumns: "1fr 1fr",
                    gap: 4,
                    padding: 4,
                    borderRadius: 999,
                    border:
                      "1px solid var(--console-border-subtle, rgba(13, 148, 136, 0.14))",
                    background: "rgba(247, 254, 252, 0.9)",
                  }}
                >
                  {[
                    { code: "en", label: "English" },
                    { code: "zh", label: "中文" },
                  ].map((item) => {
                    const active = locale === item.code;
                    return (
                      <Link
                        key={item.code}
                        href={pathname}
                        locale={item.code as "en" | "zh"}
                        style={{
                          minWidth: 96,
                          padding: "8px 16px",
                          borderRadius: 999,
                          textAlign: "center",
                          fontSize: "0.8125rem",
                          fontWeight: 800,
                          textDecoration: "none",
                          color: active
                            ? "#fff"
                            : "var(--console-text-secondary, #475569)",
                          background: active
                            ? "linear-gradient(135deg, var(--console-accent, #0D9488), var(--console-accent-secondary, #14B8A6))"
                            : "transparent",
                        }}
                      >
                        {item.label}
                      </Link>
                    );
                  })}
                </div>
              </SettingsCard>

              <SettingsCard
                icon={<Code2 size={18} />}
                title={t("settings.developerMode")}
                description={t("settings.developerModeDesc")}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 16,
                    padding: 14,
                    borderRadius: 16,
                    border:
                      "1px solid var(--console-border-subtle, rgba(13, 148, 136, 0.12))",
                    background: "rgba(247, 254, 252, 0.76)",
                  }}
                >
                  <span
                    style={{
                      fontSize: "0.875rem",
                      fontWeight: 800,
                      color: "var(--console-text-primary, #0f172a)",
                    }}
                  >
                    {isDeveloperMode
                      ? t("settings.developerModeOn")
                      : t("settings.developerModeOff")}
                  </span>
                  <button
                    role="switch"
                    aria-checked={isDeveloperMode}
                    onClick={toggleDeveloperMode}
                    style={{
                      position: "relative",
                      display: "inline-flex",
                      height: 28,
                      width: 52,
                      flexShrink: 0,
                      borderRadius: 999,
                      border: "none",
                      cursor: "pointer",
                      transition: "background 0.2s ease",
                      background: isDeveloperMode
                        ? "var(--console-accent, #0D9488)"
                        : "rgba(15, 23, 42, 0.14)",
                      padding: 0,
                    }}
                  >
                    <span
                      style={{
                        display: "inline-block",
                        height: 24,
                        width: 24,
                        borderRadius: 999,
                        background: "white",
                        boxShadow: "0 2px 8px rgba(15, 23, 42, 0.18)",
                        transform: isDeveloperMode
                          ? "translateX(26px)"
                          : "translateX(2px)",
                        transition: "transform 0.2s ease",
                        marginTop: 2,
                      }}
                    />
                  </button>
                </div>
              </SettingsCard>

              <SettingsCard
                icon={<Trash2 size={18} />}
                title={t("settings.dangerZone")}
                description={t("settings.dangerZoneDesc")}
                danger
              >
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                  <GhostButton onClick={() => void logout()}>
                    <LogOut size={15} />
                    {t("settings.logout")}
                  </GhostButton>
                  <GhostButton
                    danger
                    onClick={() => setDeleteMsg(t("settings.deleteConfirm"))}
                  >
                    <Trash2 size={15} />
                    {t("settings.deleteData")}
                  </GhostButton>
                </div>
                {deleteMsg ? (
                  <div
                    style={{
                      marginTop: 14,
                      padding: "10px 14px",
                      borderRadius: 14,
                      fontSize: "0.8125rem",
                      background: "rgba(220,38,38,0.08)",
                      color: "rgb(153,27,27)",
                      border: "1px solid rgba(220,38,38,0.14)",
                    }}
                  >
                    {deleteMsg}
                  </div>
                ) : null}
              </SettingsCard>
            </div>
          </div>
        </div>
      </div>
    </PageTransition>
  );
}
