"use client";

import { useCallback, useRef } from "react";
import { ROLE_CONTENT, ROLE_KEYS, type RoleKey } from "@/lib/marketing/role-content";
import RoleIcon from "./RoleIcon";

interface Props {
  activeRole: RoleKey | null;
  onSelect: (role: RoleKey) => void;
  locale: "zh" | "en";
  groupLabel: string;
}

export default function RoleChipRow({ activeRole, onSelect, locale, groupLabel }: Props) {
  const chipsRef = useRef<Array<HTMLButtonElement | null>>([]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        e.preventDefault();
        const delta = e.key === "ArrowRight" ? 1 : -1;
        const nextIndex = (index + delta + ROLE_KEYS.length) % ROLE_KEYS.length;
        const nextRole = ROLE_KEYS[nextIndex];
        onSelect(nextRole);
        chipsRef.current[nextIndex]?.focus();
      }
    },
    [onSelect],
  );

  return (
    <div role="radiogroup" aria-label={groupLabel} className="marketing-exclusive__chips">
      {ROLE_KEYS.map((key, i) => {
        const content = ROLE_CONTENT[key];
        const isActive = activeRole === key;
        return (
          <button
            key={key}
            ref={(el) => { chipsRef.current[i] = el; }}
            type="button"
            role="radio"
            aria-checked={isActive}
            aria-label={content.label[locale]}
            tabIndex={isActive || (!activeRole && i === 0) ? 0 : -1}
            data-active={isActive || undefined}
            className="marketing-exclusive__chip"
            onClick={() => onSelect(key)}
            onKeyDown={(e) => handleKeyDown(e, i)}
          >
            <span className="marketing-exclusive__chip-icon">
              <RoleIcon iconKey={content.iconKey} size={20} />
            </span>
            <span className="marketing-exclusive__chip-label">{content.label[locale]}</span>
            <span className="marketing-exclusive__chip-sub">{content.domainNoun[locale]}</span>
          </button>
        );
      })}
    </div>
  );
}
