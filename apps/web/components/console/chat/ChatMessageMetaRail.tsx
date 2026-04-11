"use client";

import type {
  ChatMetaRailItem,
  InspectorSection,
  InspectorTab,
} from "../chat-types";

interface ChatMessageMetaRailProps {
  items: ChatMetaRailItem[];
  onOpenInspector: (payload: {
    tab: InspectorTab;
    messageId: string;
    section?: InspectorSection;
  }) => void;
  messageId: string;
}

export function ChatMessageMetaRail({
  items,
  onOpenInspector,
  messageId,
}: ChatMessageMetaRailProps) {
  if (!items.length) {
    return null;
  }

  return (
    <div className="chat-meta-rail" aria-label="Message metadata">
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          className={`chat-meta-chip chat-meta-chip--${item.key}`}
          onClick={() =>
            onOpenInspector({
              tab: item.tab,
              section: item.section,
              messageId,
            })
          }
        >
          <span className="chat-meta-chip-label">{item.label}</span>
        </button>
      ))}
    </div>
  );
}
