"use client";

import React from "react";
import type { LucideIcon } from "lucide-react";
import type { Hit } from "@/hooks/useSearch";

interface Props {
  heading: string;
  // `LucideIcon` carries the `size`/`className`/`strokeWidth` prop typing.
  // Plain `React.ElementType` widens its props to `unknown`/`never` under
  // @types/react@19, which causes `<Icon size={N} />` to fail typecheck.
  icon: LucideIcon;
  items: Hit[];
  onPick: (hit: Hit) => void;
  emptyHint?: string;
}

export default function SearchResultsGroup({
  heading, icon: Icon, items, onPick, emptyHint,
}: Props) {
  return (
    <section className="search-group">
      <h3 className="search-group__heading">
        <Icon size={13} />
        <span>{heading}</span>
        <span className="search-group__count">{items.length}</span>
      </h3>
      {items.length === 0 ? (
        <p className="search-group__empty">{emptyHint || "—"}</p>
      ) : (
        <ul className="search-group__list">
          {items.map((hit, i) => (
            <li
              key={
                hit.id || hit.asset_id || hit.memory_view_id ||
                `${heading}-${i}`
              }
              data-testid="search-result-item"
              className="search-group__item"
              onClick={() => onPick(hit)}
            >
              <div className="search-group__title">
                {hit.title || hit.snippet?.slice(0, 60) || "(untitled)"}
              </div>
              {hit.snippet && hit.snippet !== hit.title && (
                <div className="search-group__snippet">
                  {hit.snippet.slice(0, 140)}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
