"use client";

import type { InspectorTab } from "../chat-types";

type InspectorTabOption = {
  key: InspectorTab;
  label: string;
};

interface ConversationInspectorTabsProps {
  activeTab: InspectorTab;
  options: InspectorTabOption[];
  onTabChange: (tab: InspectorTab) => void;
}

export function ConversationInspectorTabs({
  activeTab,
  options,
  onTabChange,
}: ConversationInspectorTabsProps) {
  return (
    <div className="chat-inspector-tabs" role="tablist" aria-label="Inspector">
      {options.map((option) => {
        const active = option.key === activeTab;
        return (
          <button
            key={option.key}
            type="button"
            role="tab"
            aria-selected={active}
            className={`chat-inspector-tab${active ? " is-active" : ""}`}
            onClick={() => onTabChange(option.key)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
