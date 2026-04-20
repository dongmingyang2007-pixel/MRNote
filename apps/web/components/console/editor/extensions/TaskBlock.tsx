"use client";

import { Node, mergeAttributes } from "@tiptap/core";
import type { NodeViewProps } from "@tiptap/react";
import { NodeViewWrapper, ReactNodeViewRenderer } from "@tiptap/react";
import { useCallback, useState } from "react";
import { CalendarDays, MoreVertical } from "lucide-react";
import { useTranslations } from "next-intl";
import { apiPost } from "@/lib/api";
import { useCurrentPageId } from "@/components/console/editor/PageIdContext";

interface TaskAttrs {
  block_id: string;
  title: string;
  description: string | null;
  due_date: string | null;
  completed: boolean;
  completed_at: string | null;
}

function TaskBlockView(props: NodeViewProps) {
  const t = useTranslations("console-notebooks");
  const attrs = props.node.attrs as TaskAttrs;
  const [expanded, setExpanded] = useState(false);
  const [failed, setFailed] = useState(false);
  const pageId = useCurrentPageId();

  const handleToggle = useCallback(async () => {
    const nextCompleted = !attrs.completed;
    const nextCompletedAt = nextCompleted ? new Date().toISOString() : null;
    // Optimistic flip.
    props.updateAttributes({ completed: nextCompleted, completed_at: nextCompletedAt });
    setFailed(false);

    if (!pageId || !attrs.block_id) return;
    try {
      await apiPost(
        `/api/v1/pages/${pageId}/tasks/${attrs.block_id}/complete`,
        { completed: nextCompleted, completed_at: nextCompletedAt },
      );
    } catch {
      // Roll back.
      props.updateAttributes({ completed: attrs.completed, completed_at: attrs.completed_at });
      setFailed(true);
    }
  }, [attrs, props, pageId]);

  return (
    <NodeViewWrapper className="task-block" data-testid="task-block">
      <div className="task-block__row">
        <input
          type="checkbox"
          checked={attrs.completed}
          onChange={handleToggle}
          data-testid="task-block-checkbox"
        />
        <input
          type="text"
          className="task-block__title"
          value={attrs.title}
          placeholder={t("block.task.titlePlaceholder")}
          onChange={(e) => props.updateAttributes({ title: e.target.value })}
        />
        {attrs.due_date && (
          <span className="task-block__due">
            <CalendarDays size={12} /> {attrs.due_date}
          </span>
        )}
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="task-block__menu"
          title={t("block.task.detailsTitle")}
        >
          <MoreVertical size={14} />
        </button>
      </div>
      {expanded && (
        <div className="task-block__expanded">
          <textarea
            placeholder={t("block.task.descriptionPlaceholder")}
            value={attrs.description ?? ""}
            onChange={(e) =>
              props.updateAttributes({ description: e.target.value || null })
            }
          />
          <input
            type="date"
            value={attrs.due_date ?? ""}
            onChange={(e) =>
              props.updateAttributes({ due_date: e.target.value || null })
            }
          />
        </div>
      )}
      {failed && <p className="task-block__error">{t("block.task.saveError")}</p>}
    </NodeViewWrapper>
  );
}

const TaskBlock = Node.create({
  name: "task",
  group: "block",
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      block_id: { default: "" },
      title: { default: "" },
      description: { default: null as string | null },
      due_date: { default: null as string | null },
      completed: { default: false },
      completed_at: { default: null as string | null },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-type="task"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-type": "task" })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(TaskBlockView);
  },
});

export default TaskBlock;
