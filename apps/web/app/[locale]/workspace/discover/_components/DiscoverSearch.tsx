"use client";

import { SearchIcon } from "./discover-icons";

interface DiscoverSearchProps {
  value: string;
  placeholder: string;
  clearLabel: string;
  onChange: (value: string) => void;
  onClear: () => void;
}

export function DiscoverSearch({
  value,
  placeholder,
  clearLabel,
  onChange,
  onClear,
}: DiscoverSearchProps) {
  return (
    <label className="dhub-search-shell">
      <span className="dhub-search-icon" aria-hidden="true">
        <SearchIcon />
      </span>
      <input
        className="dhub-search-input"
        type="text"
        aria-label={placeholder}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      {value.trim() ? (
        <button type="button" className="dhub-search-clear" onClick={onClear}>
          {clearLabel}
        </button>
      ) : null}
    </label>
  );
}
