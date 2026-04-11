"use client";

import { useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import type { MemoryNode } from "@/hooks/useGraphData";

interface ContextMenuActions {
  onViewDetail: (node: MemoryNode) => void;
  onEdit: (node: MemoryNode) => void;
  onPromote: (id: string) => void;
  onDelete: (id: string) => void;
  onAddMemory: () => void;
}

interface GraphContextMenuProps {
  x: number;
  y: number;
  node: MemoryNode | null;
  visible: boolean;
  onClose: () => void;
  actions: ContextMenuActions;
}

function isFileNode(node: MemoryNode): boolean {
  return node.category === "file" || node.category === "文件" || node.metadata_json?.node_kind === "file";
}

export default function GraphContextMenu({
  x,
  y,
  node,
  visible,
  onClose,
  actions,
}: GraphContextMenuProps) {
  const t = useTranslations("console-assistants");
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!visible) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [visible, onClose]);

  useEffect(() => {
    if (!visible) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [visible, onClose]);

  if (!visible) return null;

  return (
    <div
      ref={menuRef}
      className="graph-context-menu"
      style={{ left: x, top: y }}
    >
      {node ? (
        <>
          <button
            className="graph-context-item"
            onClick={() => {
              actions.onViewDetail(node);
              onClose();
            }}
          >
            {t("graph.viewDetail")}
          </button>
          {!isFileNode(node) && (
            <button
              className="graph-context-item"
              onClick={() => {
                actions.onEdit(node);
                onClose();
              }}
            >
              {t("graph.edit")}
            </button>
          )}
          {!isFileNode(node) && node.type === "temporary" && (
            <button
              className="graph-context-item"
              onClick={() => {
                actions.onPromote(node.id);
                onClose();
              }}
            >
              {t("graph.promote")}
            </button>
          )}
          {!isFileNode(node) && (
            <button
              className="graph-context-item is-danger"
              onClick={() => {
                actions.onDelete(node.id);
                onClose();
              }}
            >
              {t("graph.delete")}
            </button>
          )}
        </>
      ) : (
        <button
          className="graph-context-item"
          onClick={() => {
            actions.onAddMemory();
            onClose();
          }}
        >
          {t("graph.addMemory")}
        </button>
      )}
    </div>
  );
}
