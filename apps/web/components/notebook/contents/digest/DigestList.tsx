"use client";

import { useCallback, useEffect, useState } from "react";
import { Bell, Calendar, Flag, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import { apiGet } from "@/lib/api";

interface Digest {
  id: string;
  kind: string;
  title: string;
  period_start: string;
  period_end: string;
  status: string;
  created_at: string;
}

interface Props {
  kind?: string;
  status?: string;
  onPick: (digest: Digest) => void;
}

const KIND_ICON: Record<string, React.ElementType> = {
  daily_digest: Calendar,
  weekly_reflection: Bell,
  deviation_reminder: Flag,
  relationship_reminder: Users,
};

export default function DigestList({ kind, status, onPick }: Props) {
  const t = useTranslations("console-notebooks");
  const [items, setItems] = useState<Digest[]>([]);
  const [loading, setLoading] = useState(true);

  const relTime = (iso: string): string => {
    const diff = Date.now() - new Date(iso).getTime();
    const days = Math.floor(diff / 86400000);
    if (days === 0) return t("digest.relTime.today");
    if (days === 1) return t("digest.relTime.yesterday");
    if (days < 7) return t("digest.relTime.daysAgo", { days });
    return t("digest.relTime.weeksAgo", { weeks: Math.floor(days / 7) });
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (kind) params.set("kind", kind);
      if (status) params.set("status", status);
      params.set("limit", "50");
      const data = await apiGet<{ items: Digest[]; next_cursor: string | null }>(
        `/api/v1/digests?${params.toString()}`,
      );
      setItems(data.items || []);
    } catch {
      setItems([]);
    }
    setLoading(false);
  }, [kind, status]);

  useEffect(() => { void load(); }, [load]);

  if (loading) {
    return <p style={{ padding: 12, fontSize: 12, color: "#888" }}>{t("digest.loading")}</p>;
  }

  if (items.length === 0) {
    return (
      <p style={{ padding: 12, fontSize: 12, color: "#888" }}>
        {t("digest.empty")}
      </p>
    );
  }

  return (
    <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
      {items.map((it) => {
        const Icon = KIND_ICON[it.kind] ?? Bell;
        return (
          <li
            key={it.id}
            data-testid="digest-list-item"
            onClick={() => onPick(it)}
            style={{
              padding: 10,
              borderBottom: "1px solid #eee",
              cursor: "pointer",
              display: "flex",
              gap: 8,
              alignItems: "flex-start",
            }}
          >
            <Icon size={16} style={{ marginTop: 2, flexShrink: 0, color: "#6b7280" }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 600, display: "flex", alignItems: "center", gap: 6 }}>
                {it.status === "unread" && (
                  <span
                    data-testid="digest-unread-dot"
                    style={{ width: 8, height: 8, borderRadius: 999, background: "#2563eb" }}
                  />
                )}
                {it.title}
              </div>
              <div style={{ fontSize: 11, color: "#9ca3af" }}>
                {it.kind} · {relTime(it.created_at)}
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
