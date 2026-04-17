"use client";

import { useEffect, useState } from "react";

interface PlanRequiredDetail {
  code?: string;
  message?: string;
  details?: { key?: string; current?: number; limit?: number };
}

export default function UpgradeModal() {
  const [detail, setDetail] = useState<PlanRequiredDetail | null>(null);

  useEffect(() => {
    const handler = (e: Event) => {
      const ce = e as CustomEvent<PlanRequiredDetail>;
      setDetail(ce.detail || {});
    };
    window.addEventListener("mrai:plan-required", handler);
    return () => window.removeEventListener("mrai:plan-required", handler);
  }, []);

  if (!detail) return null;

  const handleUpgrade = () => {
    window.location.href = "/workspace/settings/billing";
  };

  return (
    <div
      data-testid="upgrade-modal"
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
        zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center",
      }}
    >
      <div style={{
        background: "#fff", borderRadius: 8, padding: 24,
        maxWidth: 420, width: "90%",
      }}>
        <h2 style={{ marginTop: 0 }}>Upgrade required</h2>
        <p>{detail.message || "Please upgrade your plan to continue."}</p>
        {detail.details?.key && (
          <p style={{ fontSize: 12, color: "#6b7280" }}>
            Limit: <strong>{detail.details.key}</strong>
            {detail.details.current !== undefined && detail.details.limit !== undefined && (
              <> ({detail.details.current}/{detail.details.limit})</>
            )}
          </p>
        )}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 16 }}>
          <button
            type="button"
            onClick={() => setDetail(null)}
            style={{ padding: "6px 12px", background: "transparent", border: "1px solid #d1d5db", borderRadius: 6, cursor: "pointer" }}
          >
            Dismiss
          </button>
          <button
            type="button"
            onClick={handleUpgrade}
            data-testid="upgrade-modal-go"
            style={{ padding: "6px 12px", background: "#2563eb", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer" }}
          >
            See plans
          </button>
        </div>
      </div>
    </div>
  );
}
