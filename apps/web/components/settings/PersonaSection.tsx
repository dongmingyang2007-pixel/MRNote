"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Check } from "lucide-react";

import { GlassCard } from "@/components/console/glass";
import { toast } from "@/hooks/use-toast";
import { apiGet, apiPatch, isApiRequestError } from "@/lib/api";
import { isPersonaKey, PERSONA_KEYS, type PersonaKey } from "@/lib/persona";

interface AuthMe {
  id: string;
  email: string;
  persona?: PersonaKey | null;
}

/** Account-settings "Role" / "身份" card. Sits inside the main settings page
 *  hub, alongside Account / Language / Developer Mode / etc. The field
 *  drives the server-side `users.persona` value used by digest generation
 *  and role-personalized offers. Kept as a self-contained component so the
 *  parent page stays readable. */
export default function PersonaSection() {
  const tAuth = useTranslations("auth");
  const tSettings = useTranslations("console-settings");
  const [persona, setPersonaState] = useState<PersonaKey | null>(null);
  const [savedPersona, setSavedPersona] = useState<PersonaKey | null>(null);
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    void apiGet<AuthMe>("/api/v1/auth/me")
      .then((me) => {
        const serverPersona = isPersonaKey(me.persona) ? me.persona : null;
        setPersonaState(serverPersona);
        setSavedPersona(serverPersona);
      })
      .catch(() => {
        // Silent fail: guests shouldn't land here, and backend not-yet-deployed
        // should still show the card so the user can pick a value once the
        // endpoint is live.
      })
      .finally(() => setLoaded(true));
  }, []);

  const dirty = persona !== savedPersona;

  const handleSave = useCallback(async () => {
    if (saving) return;
    setSaving(true);
    try {
      await apiPatch<AuthMe>("/api/v1/auth/me", { persona });
      setSavedPersona(persona);
      toast({ title: tSettings("persona.saved") });
    } catch (err) {
      const msg =
        isApiRequestError(err) && err.status === 404
          ? tSettings("persona.error") // endpoint not deployed — generic error still clearer than stack
          : tSettings("persona.error");
      toast({ title: msg, description: isApiRequestError(err) ? err.message : undefined });
    } finally {
      setSaving(false);
    }
  }, [persona, saving, tSettings]);

  const handleClear = useCallback(() => {
    setPersonaState(null);
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

  return (
    <GlassCard>
      <div style={sectionTitle}>{tSettings("persona.title")}</div>
      <p style={{ ...sectionDesc, marginBottom: 14 }}>{tSettings("persona.description")}</p>

      <div
        role="radiogroup"
        aria-label={tAuth("me.persona.label")}
        style={{ display: "flex", gap: 8, flexWrap: "wrap" }}
      >
        {PERSONA_KEYS.map((key) => {
          const active = persona === key;
          return (
            <button
              key={key}
              type="button"
              role="radio"
              aria-checked={active}
              disabled={!loaded || saving}
              onClick={() => setPersonaState(key)}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "6px 14px",
                borderRadius: 9999,
                fontSize: 13,
                fontWeight: 500,
                cursor: loaded && !saving ? "pointer" : "default",
                transition: "all 0.15s ease",
                background: active
                  ? "linear-gradient(135deg, var(--console-accent, var(--accent)), color-mix(in srgb, var(--console-accent, var(--accent)) 80%, white))"
                  : "var(--console-surface, rgba(255,255,255,0.06))",
                border: active
                  ? "1px solid transparent"
                  : "1px solid var(--console-border, var(--border))",
                color: active
                  ? "#fff"
                  : "var(--console-text-primary, var(--text-primary))",
              }}
            >
              {active ? <Check size={12} aria-hidden="true" /> : null}
              <span>{tAuth(`me.persona.${key}`)}</span>
            </button>
          );
        })}
      </div>

      <div
        style={{
          marginTop: 14,
          display: "flex",
          gap: 8,
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        <button
          type="button"
          onClick={handleSave}
          disabled={!dirty || saving || !loaded}
          style={{
            padding: "7px 18px",
            fontSize: 13,
            fontWeight: 500,
            borderRadius: 9999,
            border: "1px solid transparent",
            background:
              dirty && !saving
                ? "linear-gradient(135deg, var(--console-accent, var(--accent)), color-mix(in srgb, var(--console-accent, var(--accent)) 80%, white))"
                : "var(--console-surface, rgba(255,255,255,0.06))",
            color: dirty && !saving ? "#fff" : "var(--console-text-secondary, var(--text-secondary))",
            cursor: dirty && !saving ? "pointer" : "not-allowed",
            transition: "all 0.15s ease",
          }}
        >
          {saving ? tSettings("settings.loadingUser") : tSettings("persona.save")}
        </button>
        <button
          type="button"
          onClick={handleClear}
          disabled={persona === null || saving || !loaded}
          style={{
            padding: "7px 14px",
            fontSize: 13,
            fontWeight: 500,
            borderRadius: 9999,
            border: "1px solid var(--console-border, var(--border))",
            background: "transparent",
            color: "var(--console-text-secondary, var(--text-secondary))",
            cursor: persona && !saving ? "pointer" : "not-allowed",
            transition: "all 0.15s ease",
          }}
        >
          {tAuth("me.persona.clear")}
        </button>
      </div>
    </GlassCard>
  );
}
