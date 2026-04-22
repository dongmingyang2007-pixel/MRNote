"use client";

import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { logout } from "@/lib/api";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export default function UserMenu() {
  const t = useTranslations("marketing");
  const tCommon = useTranslations("common");

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="marketing-user-menu__avatar"
          aria-label={t("userMenu.ariaLabel")}
          data-testid="marketing-user-menu"
        >
          U
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" sideOffset={8}>
        <DropdownMenuItem asChild>
          <Link href="/app/settings">{tCommon("user.settings")}</Link>
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => void logout()}>
          {tCommon("user.logout")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
