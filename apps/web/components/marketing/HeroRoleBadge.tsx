"use client";

import { useRoleContext } from "@/lib/marketing/RoleContext";
import { ROLE_CONTENT } from "@/lib/marketing/role-content";
import { useTranslations } from "next-intl";

interface Props {
  locale: "zh" | "en";
}

export default function HeroRoleBadge({ locale }: Props) {
  const { role } = useRoleContext();
  const t = useTranslations("marketing");
  if (!role) return null;
  const label = ROLE_CONTENT[role].label[locale];
  return (
    <span data-testid="hero-role-badge" className="marketing-hero__role-badge">
      <span aria-hidden="true">✨</span> {t("hero.forRole", { role: label })}
    </span>
  );
}
