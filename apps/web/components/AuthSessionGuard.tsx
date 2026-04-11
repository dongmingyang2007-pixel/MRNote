"use client";

import { useEffect, useRef } from "react";
import { useTranslations } from "next-intl";

import { toast } from "@/hooks/use-toast";
import { AUTH_SESSION_EXPIRED_EVENT } from "@/lib/api";

export function AuthSessionGuard() {
  const t = useTranslations("common");
  const lastToastAtRef = useRef(0);

  useEffect(() => {
    const onSessionExpired = () => {
      const now = Date.now();
      if (now - lastToastAtRef.current < 800) {
        return;
      }
      lastToastAtRef.current = now;
      toast({
        title: t("session.expiredTitle"),
        description: t("session.expiredBody"),
      });
    };

    window.addEventListener(
      AUTH_SESSION_EXPIRED_EVENT,
      onSessionExpired as EventListener,
    );

    return () => {
      window.removeEventListener(
        AUTH_SESSION_EXPIRED_EVENT,
        onSessionExpired as EventListener,
      );
    };
  }, [t]);

  return null;
}
