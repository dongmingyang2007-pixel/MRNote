"use client";

import { useEffect, useState } from "react";
import { useLocale } from "next-intl";
import { ArrowRight, Lock } from "lucide-react";

import { Link } from "@/i18n/navigation";

type Locale = "zh" | "en";
type GateReason =
  | "save"
  | "upload"
  | "ai"
  | "memory"
  | "search"
  | "newPage"
  | "settings"
  | "digest";

export const GUEST_REGISTER_GATE_EVENT = "mrnote:guest-register-gate";

export function requestGuestRegisterGate(reason: GateReason): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent(GUEST_REGISTER_GATE_EVENT, { detail: { reason } }),
  );
}

function copy(locale: Locale, zh: string, en: string): string {
  return locale === "en" ? en : zh;
}

function getGateCopy(locale: Locale, reason: GateReason) {
  const table = {
    save: {
      title: copy(locale, "保存这页需要一个账号", "Create an account to save"),
      body: copy(
        locale,
        "账号会把这份草稿放进你的 notebook。之后回来，标题、正文和页面结构都会还在。",
        "Your account keeps this draft in a notebook so the title, body, and page structure are still here next time.",
      ),
    },
    upload: {
      title: copy(locale, "上传资料需要账号", "Create an account to upload"),
      body: copy(
        locale,
        "上传的文件会进入你的私人工作区，之后才能引用、检索和生成页面。",
        "Uploaded files live in your private workspace so they can be cited, searched, and turned into pages.",
      ),
    },
    ai: {
      title: copy(
        locale,
        "使用助手需要账号",
        "Create an account to use the assistant",
      ),
      body: copy(
        locale,
        "这样 MRNote 才能把回答、来源和后续操作挂回这份 notebook。",
        "That lets MRNote attach answers, sources, and follow-ups back to this notebook.",
      ),
    },
    memory: {
      title: copy(
        locale,
        "记忆图谱需要账号",
        "Create an account to use the graph",
      ),
      body: copy(
        locale,
        "图谱需要长期保存页面、来源和节点关系，必须归到你的工作区里。",
        "The graph keeps pages, sources, and node relationships over time, so it belongs in your workspace.",
      ),
    },
    search: {
      title: copy(locale, "搜索工作区需要账号", "Create an account to search"),
      body: copy(
        locale,
        "搜索会跨页面、文件、资料和图谱运行。先保存到账号后，这些内容才有稳定索引。",
        "Search spans pages, files, sources, and graph nodes. Save to an account first so that material can be indexed.",
      ),
    },
    newPage: {
      title: copy(
        locale,
        "新建更多页面需要账号",
        "Create an account to add pages",
      ),
      body: copy(
        locale,
        "未登录时可以先写当前草稿。注册后可以保存多个页面和 notebook。",
        "You can write the current draft while logged out. After signup, you can keep multiple pages and notebooks.",
      ),
    },
    settings: {
      title: copy(
        locale,
        "设置工作区需要账号",
        "Create an account to change settings",
      ),
      body: copy(
        locale,
        "主题、偏好、导出和账号设置会跟随你的工作区保存。",
        "Theme, preferences, export, and account settings are saved with your workspace.",
      ),
    },
    digest: {
      title: copy(locale, "Digest 需要账号", "Create an account to use Digest"),
      body: copy(
        locale,
        "Digest 需要读取你保存过的页面、资料和待办，才能帮你回到上下文。",
        "Digest needs saved pages, sources, and follow-ups before it can bring context back.",
      ),
    },
  } satisfies Record<GateReason, { title: string; body: string }>;

  return table[reason];
}

export default function GuestRegisterGate() {
  const locale: Locale = useLocale() === "en" ? "en" : "zh";
  const [reason, setReason] = useState<GateReason | null>(null);
  const currentGate = reason ? getGateCopy(locale, reason) : null;

  useEffect(() => {
    const handleGate = (event: Event) => {
      const detail = (event as CustomEvent<{ reason?: GateReason }>).detail;
      setReason(detail?.reason ?? "save");
    };
    window.addEventListener(GUEST_REGISTER_GATE_EVENT, handleGate);
    return () =>
      window.removeEventListener(GUEST_REGISTER_GATE_EVENT, handleGate);
  }, []);

  if (!currentGate) return null;

  return (
    <div className="guest-draft-gate" role="dialog" aria-modal="true">
      <div className="guest-draft-gate-panel">
        <button
          type="button"
          className="guest-draft-gate-close"
          onClick={() => setReason(null)}
        >
          {copy(locale, "继续写", "Keep writing")}
        </button>
        <span className="guest-draft-gate-icon">
          <Lock size={18} />
        </span>
        <h2>{currentGate.title}</h2>
        <p>{currentGate.body}</p>
        <div className="guest-draft-gate-actions">
          <Link href="/register?next=/app/notebooks">
            {copy(locale, "创建账号并保存", "Create account and save")}
            <ArrowRight size={15} />
          </Link>
          <Link href="/login?next=/app/notebooks">
            {copy(locale, "我已有账号", "I already have an account")}
          </Link>
        </div>
      </div>
    </div>
  );
}
