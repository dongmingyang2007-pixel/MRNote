"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { DISCOVER_ENABLED } from "@/lib/feature-flags";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";

const NAVIGATION_ITEMS = [
  { key: "nav.home", href: "/app" },
  { key: "nav.assistants", href: "/app/assistants" },
  { key: "nav.chat", href: "/app/chat" },
  { key: "nav.memory", href: "/app/memory" },
  ...(DISCOVER_ENABLED ? [{ key: "nav.discover", href: "/app/discover" }] : []),
  { key: "nav.settings", href: "/app/settings" },
];

const ACTION_ITEMS = [{ key: "cmd.newAssistant", href: "/app/assistants/new" }];

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const t = useTranslations("console");

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  const navigate = useCallback(
    (href: string) => {
      setOpen(false);
      router.push(href);
    },
    [router],
  );

  return (
    <CommandDialog open={open} onOpenChange={setOpen} title={t("cmd.title")}>
      <CommandInput placeholder={t("cmd.placeholder")} />
      <CommandList>
        <CommandEmpty>{t("cmd.empty")}</CommandEmpty>
        <CommandGroup heading={t("cmd.navigate")}>
          {NAVIGATION_ITEMS.map((item) => (
            <CommandItem key={item.href} onSelect={() => navigate(item.href)}>
              {t(item.key)}
            </CommandItem>
          ))}
        </CommandGroup>
        <CommandGroup heading={t("cmd.actions")}>
          {ACTION_ITEMS.map((item) => (
            <CommandItem
              key={`action-${item.href}`}
              onSelect={() => navigate(item.href)}
            >
              {t(item.key)}
            </CommandItem>
          ))}
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
