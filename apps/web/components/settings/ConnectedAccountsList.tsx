"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import {
  apiGet,
  apiPost,
  apiPut,
  isApiRequestError,
} from "@/lib/api";

interface Identity {
  id: string;
  provider: string;
  provider_email: string | null;
  linked_at: string;
}

type Phase = "idle" | "confirming" | "password_setup";

export default function ConnectedAccountsList() {
  const t = useTranslations("auth");
  const [identities, setIdentities] = useState<Identity[] | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<Identity[]>("/api/v1/auth/identities");
      setIdentities(data);
    } catch {
      setIdentities([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const google = (identities ?? []).find((i) => i.provider === "google") ?? null;

  const connect = () => {
    window.location.href =
      "/api/v1/auth/google/authorize?mode=connect&next=/app/settings";
  };

  const startDisconnect = () => {
    setError(null);
    setPhase("confirming");
  };
  const cancelDisconnect = () => {
    setPhase("idle");
    setError(null);
  };

  const confirmDisconnect = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await apiPost("/api/v1/auth/google/disconnect", {});
      setPhase("idle");
      await load();
    } catch (err: unknown) {
      if (isApiRequestError(err) && err.status === 409 && err.code === "password_required") {
        setPhase("password_setup");
      } else {
        setError(t("oauth.error.state_mismatch"));
      }
    } finally {
      setSubmitting(false);
    }
  };

  const submitPassword = async () => {
    setError(null);
    if (newPw.length < 8) {
      setError(t("connectedAccounts.setPassword.tooShort"));
      return;
    }
    if (newPw !== confirmPw) {
      setError(t("connectedAccounts.setPassword.mismatch"));
      return;
    }
    setSubmitting(true);
    // Two-step: set password, then disconnect Google. Report distinct errors
    // so the user understands which step failed (and the second step, when
    // it fails, leaves both auth methods active — we surface that).
    try {
      await apiPut("/api/v1/auth/password", { new_password: newPw });
    } catch {
      setError(t("connectedAccounts.setPassword.failed"));
      setSubmitting(false);
      return;
    }
    try {
      await apiPost("/api/v1/auth/google/disconnect", {});
    } catch {
      // Password was set. Reload so the new method shows, then flag the
      // partial failure so the user can retry disconnect.
      await load();
      setError(t("connectedAccounts.disconnectPartialFailure"));
      setSubmitting(false);
      return;
    }
    setPhase("idle");
    setNewPw("");
    setConfirmPw("");
    await load();
    setSubmitting(false);
  };

  if (identities === null) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: 12,
          border: "1px solid var(--border)",
          borderRadius: 8,
        }}
      >
        <span style={{ fontWeight: 600 }}>
          {t("connectedAccounts.google.name")}
        </span>
        {google ? (
          <>
            <span style={{ color: "var(--text-secondary)" }}>
              {google.provider_email}
            </span>
            <span style={{ color: "var(--text-secondary)", fontSize: 12 }}>
              {t("connectedAccounts.linkedAt", {
                date: new Date(google.linked_at).toLocaleDateString(),
              })}
            </span>
            <div style={{ flex: 1 }} />
            <button
              data-testid="oauth-disconnect-google"
              type="button"
              onClick={startDisconnect}
              style={{
                padding: "6px 12px",
                borderRadius: 6,
                border: "1px solid var(--border)",
                background: "transparent",
                cursor: "pointer",
              }}
            >
              {t("connectedAccounts.disconnect")}
            </button>
          </>
        ) : (
          <>
            <div style={{ flex: 1 }} />
            <button
              data-testid="oauth-connect-google"
              type="button"
              onClick={connect}
              style={{
                padding: "6px 12px",
                borderRadius: 6,
                border: "1px solid var(--border)",
                background: "var(--accent, #0d9488)",
                color: "#fff",
                cursor: "pointer",
              }}
            >
              {t("connectedAccounts.connect")}
            </button>
          </>
        )}
      </div>

      {phase === "confirming" && (
        <div
          style={{
            padding: 16,
            border: "1px solid var(--border)",
            borderRadius: 8,
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 6 }}>
            {t("connectedAccounts.disconnectConfirm.title")}
          </div>
          <div
            style={{
              color: "var(--text-secondary)",
              marginBottom: 12,
              fontSize: 13,
            }}
          >
            {t("connectedAccounts.disconnectConfirm.desc")}
          </div>
          {error && (
            <div style={{ color: "#ef4444", marginBottom: 8, fontSize: 13 }}>
              {error}
            </div>
          )}
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="button"
              onClick={cancelDisconnect}
              disabled={submitting}
              style={{
                padding: "6px 12px",
                borderRadius: 6,
                border: "1px solid var(--border)",
                background: "transparent",
                cursor: "pointer",
              }}
            >
              {t("connectedAccounts.disconnectConfirm.cancel")}
            </button>
            <button
              data-testid="oauth-disconnect-confirm"
              type="button"
              onClick={confirmDisconnect}
              disabled={submitting}
              style={{
                padding: "6px 12px",
                borderRadius: 6,
                border: "none",
                background: "#ef4444",
                color: "#fff",
                cursor: "pointer",
              }}
            >
              {t("connectedAccounts.disconnectConfirm.confirm")}
            </button>
          </div>
        </div>
      )}

      {phase === "password_setup" && (
        <form
          data-testid="oauth-set-password-form"
          onSubmit={(e) => {
            e.preventDefault();
            void submitPassword();
          }}
          style={{
            padding: 16,
            border: "1px solid var(--border)",
            borderRadius: 8,
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 6 }}>
            {t("connectedAccounts.setPassword.title")}
          </div>
          <div
            style={{
              color: "var(--text-secondary)",
              marginBottom: 12,
              fontSize: 13,
            }}
          >
            {t("connectedAccounts.setPassword.desc")}
          </div>
          <label style={{ display: "block", marginBottom: 8 }}>
            <span style={{ fontSize: 13 }}>
              {t("connectedAccounts.setPassword.newPassword")}
            </span>
            <input
              type="password"
              value={newPw}
              onChange={(e) => setNewPw(e.target.value)}
              required
              minLength={8}
              style={{
                width: "100%",
                padding: 8,
                marginTop: 4,
                borderRadius: 6,
                border: "1px solid var(--border)",
              }}
            />
          </label>
          <label style={{ display: "block", marginBottom: 8 }}>
            <span style={{ fontSize: 13 }}>
              {t("connectedAccounts.setPassword.confirmPassword")}
            </span>
            <input
              type="password"
              value={confirmPw}
              onChange={(e) => setConfirmPw(e.target.value)}
              required
              minLength={8}
              style={{
                width: "100%",
                padding: 8,
                marginTop: 4,
                borderRadius: 6,
                border: "1px solid var(--border)",
              }}
            />
          </label>
          {error && (
            <div style={{ color: "#ef4444", marginBottom: 8, fontSize: 13 }}>
              {error}
            </div>
          )}
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="button"
              onClick={cancelDisconnect}
              disabled={submitting}
              style={{
                padding: "6px 12px",
                borderRadius: 6,
                border: "1px solid var(--border)",
                background: "transparent",
                cursor: "pointer",
              }}
            >
              {t("connectedAccounts.disconnectConfirm.cancel")}
            </button>
            <button
              type="submit"
              disabled={submitting}
              style={{
                padding: "6px 12px",
                borderRadius: 6,
                border: "none",
                background: "var(--accent, #0d9488)",
                color: "#fff",
                cursor: "pointer",
              }}
            >
              {t("connectedAccounts.setPassword.submit")}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
