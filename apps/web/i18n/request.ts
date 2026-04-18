import { getRequestConfig } from "next-intl/server";
import { headers } from "next/headers";
import { routing } from "./routing";

const NAMESPACES = [
  "common",
  "auth",
  "error",
  "console",
  "console-settings",
  "console-assistants",
  "console-chat",
  "console-models-v2",
  "console-notebooks",
  "marketing",
  "legal",
  "onboarding",
] as const;

const MESSAGE_LOADERS = {
  zh: {
    common: () => import("../messages/zh/common.json"),
    auth: () => import("../messages/zh/auth.json"),
    error: () => import("../messages/zh/error.json"),
    console: () => import("../messages/zh/console.json"),
    "console-settings": () => import("../messages/zh/console-settings.json"),
    "console-assistants": () => import("../messages/zh/console-assistants.json"),
    "console-chat": () => import("../messages/zh/console-chat.json"),
    "console-models-v2": () => import("../messages/zh/console-models-v2.json"),
    "console-notebooks": () => import("../messages/zh/console-notebooks.json"),
    marketing: () => import("../messages/zh/marketing.json"),
    legal: () => import("../messages/zh/legal.json"),
    onboarding: () => import("../messages/zh/onboarding.json"),
  },
  en: {
    common: () => import("../messages/en/common.json"),
    auth: () => import("../messages/en/auth.json"),
    error: () => import("../messages/en/error.json"),
    console: () => import("../messages/en/console.json"),
    "console-settings": () => import("../messages/en/console-settings.json"),
    "console-assistants": () => import("../messages/en/console-assistants.json"),
    "console-chat": () => import("../messages/en/console-chat.json"),
    "console-models-v2": () => import("../messages/en/console-models-v2.json"),
    "console-notebooks": () => import("../messages/en/console-notebooks.json"),
    marketing: () => import("../messages/en/marketing.json"),
    legal: () => import("../messages/en/legal.json"),
    onboarding: () => import("../messages/en/onboarding.json"),
  },
} as const;

type MessageObject = Record<string, unknown>;

function isMessageObject(value: unknown): value is MessageObject {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function mergeMessages(target: MessageObject, source: MessageObject): MessageObject {
  const merged: MessageObject = { ...target };

  for (const [key, value] of Object.entries(source)) {
    const existing = merged[key];
    if (isMessageObject(existing) && isMessageObject(value)) {
      merged[key] = mergeMessages(existing, value);
    } else {
      merged[key] = value;
    }
  }

  return merged;
}

function expandDotKeys(messages: MessageObject): MessageObject {
  const expanded: MessageObject = {};

  for (const [rawKey, rawValue] of Object.entries(messages)) {
    const value = isMessageObject(rawValue) ? expandDotKeys(rawValue) : rawValue;
    const path = rawKey.split(".");

    let cursor = expanded;
    for (const segment of path.slice(0, -1)) {
      const current = cursor[segment];
      if (!isMessageObject(current)) {
        cursor[segment] = {};
      }
      cursor = cursor[segment] as MessageObject;
    }

    const leafKey = path[path.length - 1];
    const existing = cursor[leafKey];
    if (isMessageObject(existing) && isMessageObject(value)) {
      cursor[leafKey] = mergeMessages(existing, value);
    } else {
      cursor[leafKey] = value;
    }
  }

  return expanded;
}

export default getRequestConfig(async ({ requestLocale }) => {
  const requestLocaleValue = await requestLocale;
  const headerStore = await headers();
  const headerLocaleValue = headerStore.get("x-app-locale");
  const localeCandidate = requestLocaleValue ?? headerLocaleValue;
  const localeKey = localeCandidate as (typeof routing.locales)[number] | undefined;
  const locale = localeKey && routing.locales.includes(localeKey)
    ? localeKey
    : routing.defaultLocale;

  const entries = await Promise.all(
    NAMESPACES.map(async (ns) => {
      const mod = await MESSAGE_LOADERS[locale][ns]();
      return [ns, expandDotKeys(mod.default as MessageObject)] as const;
    }),
  );

  return { locale, messages: Object.fromEntries(entries) };
});
