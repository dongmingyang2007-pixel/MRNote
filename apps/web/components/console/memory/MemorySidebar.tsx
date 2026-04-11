"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { MemoryIcon, SearchIcon } from "./MemoryIcons";
import type { MemoryNode, SidebarSelection } from "./memory-types";
import {
  SMART_FOLDERS,
  CATEGORIES,
  extractSubjects,
  countByFolder,
  countByKind,
  countBySubject,
} from "./memory-types";

interface MemorySidebarProps {
  nodes: MemoryNode[];
  assistantName: string;
  selection: SidebarSelection;
  search: string;
  onSelect: (selection: SidebarSelection) => void;
  onSearchChange: (search: string) => void;
}

export default function MemorySidebar({
  nodes,
  assistantName,
  selection,
  search,
  onSelect,
  onSearchChange,
}: MemorySidebarProps) {
  const t = useTranslations("console");

  const subjects = useMemo(() => extractSubjects(nodes), [nodes]);

  const folderCounts = useMemo(
    () =>
      Object.fromEntries(
        SMART_FOLDERS.map((f) => [f.id, countByFolder(nodes, f.id)]),
      ),
    [nodes],
  );

  const categoryCounts = useMemo(
    () =>
      Object.fromEntries(
        CATEGORIES.map((c) => [c.kind, countByKind(nodes, c.kind)]),
      ),
    [nodes],
  );

  const subjectCounts = useMemo(
    () =>
      Object.fromEntries(
        subjects.map((s) => [s.id, countBySubject(nodes, s.id)]),
      ),
    [nodes, subjects],
  );

  const isActive = (type: SidebarSelection["type"], id: string) =>
    selection.type === type && selection.id === id;

  return (
    <aside className="mem-sidebar">
      <div className="mem-sidebar-header">
        <h2 className="mem-sidebar-title">{assistantName}</h2>
        <div className="mem-sidebar-search">
          <SearchIcon />
          <input
            type="text"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder={t("memory.searchPlaceholder")}
          />
        </div>
      </div>

      <nav className="mem-sidebar-nav">
        {/* Smart Folders */}
        <div className="mem-sidebar-group-label">
          {t("memory.smartFolders")}
        </div>
        {SMART_FOLDERS.map((folder) => (
          <button
            key={folder.id}
            className={`mem-sidebar-item${isActive("folder", folder.id) ? " is-active" : ""}`}
            onClick={() => onSelect({ type: "folder", id: folder.id })}
          >
            <MemoryIcon name={folder.icon} />
            <span className="mem-sidebar-item-label">
              {t(folder.labelKey)}
            </span>
            <span className="mem-sidebar-item-count">
              {folderCounts[folder.id]}
            </span>
          </button>
        ))}

        {/* Categories */}
        <div className="mem-sidebar-group-label">
          {t("memory.categories")}
        </div>
        {CATEGORIES.map((cat) => (
          <button
            key={cat.kind}
            className={`mem-sidebar-item${isActive("category", cat.kind) ? " is-active" : ""}`}
            onClick={() => onSelect({ type: "category", id: cat.kind })}
          >
            <MemoryIcon name={cat.icon} />
            <span className="mem-sidebar-item-label">
              {t(cat.labelKey)}
            </span>
            <span className="mem-sidebar-item-count">
              {categoryCounts[cat.kind]}
            </span>
          </button>
        ))}

        {/* Subjects (only if any exist) */}
        {subjects.length > 0 && (
          <>
            <div className="mem-sidebar-group-label">
              {t("memory.subjects")}
            </div>
            {subjects.map((node) => (
              <button
                key={node.id}
                className={`mem-sidebar-item${isActive("subject", node.id) ? " is-active" : ""}`}
                onClick={() => onSelect({ type: "subject", id: node.id })}
              >
                <MemoryIcon name="layers" />
                <span className="mem-sidebar-item-label">
                  {node.content}
                </span>
                <span className="mem-sidebar-item-count">
                  {subjectCounts[node.id]}
                </span>
              </button>
            ))}
          </>
        )}
      </nav>
    </aside>
  );
}
