"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

interface Me {
  entitlements: Record<string, number | boolean>;
  usage_this_month: Record<string, number>;
}

export default function UsageMeter() {
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    void apiGet<Me>("/api/v1/billing/me")
      .then(setMe)
      .catch(() => setMe(null));
  }, []);

  if (!me) return null;

  const items: Array<{ label: string; current: number; limit: number | boolean | undefined }> = [
    { label: "AI actions (this month)", current: me.usage_this_month["ai.actions"] || 0, limit: me.entitlements["ai.actions.monthly"] as number },
    { label: "Notebooks", current: me.usage_this_month["notebooks"] || 0, limit: me.entitlements["notebooks.max"] as number },
    { label: "Pages", current: me.usage_this_month["pages"] || 0, limit: me.entitlements["pages.max"] as number },
    { label: "Study assets", current: me.usage_this_month["study_assets"] || 0, limit: me.entitlements["study_assets.max"] as number },
  ];

  return (
    <section className="usage-meter" data-testid="usage-meter">
      <h2 className="usage-meter__title">Usage</h2>
      <ul>
        {items.map((it, i) => {
          const limit = typeof it.limit === "number" ? it.limit : 0;
          const cap = limit === -1 ? "∞" : String(limit);
          const pct = limit === -1 || limit === 0
            ? 0
            : Math.min(100, Math.round((it.current / limit) * 100));
          return (
            <li key={i} className="usage-meter__item">
              <div className="usage-meter__label">
                {it.label}: {it.current} / {cap}
              </div>
              <div className="usage-meter__bar">
                <div
                  className="usage-meter__fill"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
