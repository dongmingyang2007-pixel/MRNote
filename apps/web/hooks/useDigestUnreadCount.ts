"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

export function useDigestUnreadCount(): number {
  const [count, setCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function tick() {
      try {
        const r = await apiGet<{ unread_count: number }>(
          "/api/v1/digests/unread-count",
        );
        if (!cancelled) setCount(r.unread_count);
      } catch {
        /* swallow */
      }
    }
    void tick();
    const handle = setInterval(tick, 30_000);
    return () => {
      cancelled = true;
      clearInterval(handle);
    };
  }, []);

  return count;
}
