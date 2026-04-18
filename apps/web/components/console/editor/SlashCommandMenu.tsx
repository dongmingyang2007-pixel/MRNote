"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Extension } from "@tiptap/core";
import { ReactRenderer } from "@tiptap/react";
import Suggestion, { type SuggestionOptions } from "@tiptap/suggestion";
import { useTranslations } from "next-intl";
import tippy, { type Instance as TippyInstance } from "tippy.js";
import type { Editor, Range } from "@tiptap/core";
import {
  Heading1,
  Heading2,
  Heading3,
  List,
  ListOrdered,
  CheckSquare,
  Code,
  Quote,
  Minus,
  ImageIcon,
  Sigma,
  AlertCircle,
  Type,
  PenTool,
  FileUp,
  Sparkles,
  Link2,
  CheckCircle2,
  Layers,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Command item metadata (i18n keys on console-notebooks namespace)
// ---------------------------------------------------------------------------

interface SlashCommandItem {
  id: string;
  titleKey: string;
  descKey: string;
  icon: React.ElementType;
  /** When invoked, the TipTap range is already deleted. Use the editor
   * chain to insert the desired block. The translator is passed so
   * commands that need localized prompts (e.g. image URL) can use it. */
  run: (editor: Editor, t: (key: string) => string) => void;
}

const COMMANDS: SlashCommandItem[] = [
  {
    id: "h1",
    titleKey: "slash.h1.title",
    descKey: "slash.h1.desc",
    icon: Heading1,
    run: (editor) => editor.chain().focus().toggleHeading({ level: 1 }).run(),
  },
  {
    id: "h2",
    titleKey: "slash.h2.title",
    descKey: "slash.h2.desc",
    icon: Heading2,
    run: (editor) => editor.chain().focus().toggleHeading({ level: 2 }).run(),
  },
  {
    id: "h3",
    titleKey: "slash.h3.title",
    descKey: "slash.h3.desc",
    icon: Heading3,
    run: (editor) => editor.chain().focus().toggleHeading({ level: 3 }).run(),
  },
  {
    id: "p",
    titleKey: "slash.p.title",
    descKey: "slash.p.desc",
    icon: Type,
    run: (editor) => editor.chain().focus().setParagraph().run(),
  },
  {
    id: "bullet",
    titleKey: "slash.bullet.title",
    descKey: "slash.bullet.desc",
    icon: List,
    run: (editor) => editor.chain().focus().toggleBulletList().run(),
  },
  {
    id: "ordered",
    titleKey: "slash.ordered.title",
    descKey: "slash.ordered.desc",
    icon: ListOrdered,
    run: (editor) => editor.chain().focus().toggleOrderedList().run(),
  },
  {
    id: "task",
    titleKey: "slash.task.title",
    descKey: "slash.task.desc",
    icon: CheckSquare,
    run: (editor) => editor.chain().focus().toggleTaskList().run(),
  },
  {
    id: "code",
    titleKey: "slash.code.title",
    descKey: "slash.code.desc",
    icon: Code,
    run: (editor) => editor.chain().focus().toggleCodeBlock().run(),
  },
  {
    id: "quote",
    titleKey: "slash.quote.title",
    descKey: "slash.quote.desc",
    icon: Quote,
    run: (editor) => editor.chain().focus().toggleBlockquote().run(),
  },
  {
    id: "divider",
    titleKey: "slash.divider.title",
    descKey: "slash.divider.desc",
    icon: Minus,
    run: (editor) => editor.chain().focus().setHorizontalRule().run(),
  },
  {
    id: "image",
    titleKey: "slash.image.title",
    descKey: "slash.image.desc",
    icon: ImageIcon,
    run: (editor, t) => {
      const url = window.prompt(t("slash.image.prompt"));
      if (url) {
        editor.chain().focus().setImage({ src: url }).run();
      }
    },
  },
  {
    id: "math",
    titleKey: "slash.math.title",
    descKey: "slash.math.desc",
    icon: Sigma,
    run: (editor) => {
      editor
        .chain()
        .focus()
        .insertContent({ type: "mathBlock", attrs: { latex: "" } })
        .run();
    },
  },
  {
    id: "inlineMath",
    titleKey: "slash.inlineMath.title",
    descKey: "slash.inlineMath.desc",
    icon: Sigma,
    run: (editor) => {
      editor
        .chain()
        .focus()
        .insertContent({ type: "inlineMath", attrs: { latex: "" } })
        .run();
    },
  },
  {
    id: "callout",
    titleKey: "slash.callout.title",
    descKey: "slash.callout.desc",
    icon: AlertCircle,
    run: (editor) => {
      editor
        .chain()
        .focus()
        .insertContent({
          type: "callout",
          attrs: { variant: "info" },
          content: [{ type: "paragraph" }],
        })
        .run();
    },
  },
  {
    id: "whiteboard",
    titleKey: "slash.whiteboard.title",
    descKey: "slash.whiteboard.desc",
    icon: PenTool,
    run: (editor) => {
      editor
        .chain()
        .focus()
        .insertContent({
          type: "whiteboard",
          attrs: { elements: [], appState: {}, width: 600, height: 400 },
        })
        .run();
    },
  },
  {
    id: "file",
    titleKey: "slash.file.title",
    descKey: "slash.file.desc",
    icon: FileUp,
    run: (editor) =>
      editor.chain().focus().insertContent({ type: "file" }).run(),
  },
  {
    id: "aiOutput",
    titleKey: "slash.aiOutput.title",
    descKey: "slash.aiOutput.desc",
    icon: Sparkles,
    run: (editor) =>
      editor
        .chain()
        .focus()
        .insertContent({
          type: "ai_output",
          attrs: { content_markdown: "", action_type: "", action_log_id: "" },
        })
        .run(),
  },
  {
    id: "reference",
    titleKey: "slash.reference.title",
    descKey: "slash.reference.desc",
    icon: Link2,
    run: (editor) =>
      editor.chain().focus().insertContent({ type: "reference" }).run(),
  },
  {
    id: "standaloneTask",
    titleKey: "slash.standaloneTask.title",
    descKey: "slash.standaloneTask.desc",
    icon: CheckCircle2,
    run: (editor) =>
      editor
        .chain()
        .focus()
        .insertContent({
          type: "task",
          attrs: {
            block_id: crypto.randomUUID(),
            title: "",
            description: null,
            due_date: null,
            completed: false,
            completed_at: null,
          },
        })
        .run(),
  },
  {
    id: "flashcard",
    titleKey: "slash.flashcard.title",
    descKey: "slash.flashcard.desc",
    icon: Layers,
    run: (editor) =>
      editor
        .chain()
        .focus()
        .insertContent({
          type: "flashcard",
          attrs: { front: "", back: "", flipped: false },
        })
        .run(),
  },
];

// ---------------------------------------------------------------------------
// Command List Component (rendered inside tippy popup)
// ---------------------------------------------------------------------------

interface CommandListProps {
  /** All commands (unfiltered). Filtering runs inside the component so
   * the translated title drives the match, not the raw key. */
  items: SlashCommandItem[];
  /** The current text after the "/" slash character. */
  query: string;
  /** TipTap's hook to actually run the command. Passing a SlashCommandItem
   * here forwards to the top-level `command` handler in the suggestion
   * config, which deletes the slash range and then calls `item.run`. */
  command: (item: SlashCommandItem) => void;
}

interface CommandListRef {
  onKeyDown: (props: { event: KeyboardEvent }) => boolean;
}

const CommandListComponent = ({
  items,
  query,
  command,
  ref,
}: CommandListProps & { ref: React.Ref<CommandListRef> }) => {
  const t = useTranslations("console-notebooks");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  const filteredItems = useMemo(() => {
    const q = (query || "").trim().toLowerCase();
    if (!q) return items;
    return items.filter((item) => {
      const title = t(item.titleKey).toLowerCase();
      return title.includes(q);
    });
  }, [items, query, t]);

  const activeIndex =
    filteredItems.length === 0 ? 0 : Math.min(selectedIndex, filteredItems.length - 1);

  // Reset selection when the filtered list changes (e.g. user types more).
  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  // Scroll selected item into view
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const selected = container.children[activeIndex] as HTMLElement | undefined;
    if (selected) {
      selected.scrollIntoView({ block: "nearest" });
    }
  }, [activeIndex]);

  const selectItem = useCallback(
    (index: number) => {
      const item = filteredItems[index];
      if (item) command(item);
    },
    [filteredItems, command],
  );

  // Expose keyboard handler to tippy
  useEffect(() => {
    if (typeof ref === "function") {
      ref({
        onKeyDown: ({ event }: { event: KeyboardEvent }) => {
          if (event.key === "ArrowUp") {
            if (filteredItems.length === 0) {
              return true;
            }
            setSelectedIndex((i) => (i + filteredItems.length - 1) % filteredItems.length);
            return true;
          }
          if (event.key === "ArrowDown") {
            if (filteredItems.length === 0) {
              return true;
            }
            setSelectedIndex((i) => (i + 1) % filteredItems.length);
            return true;
          }
          if (event.key === "Enter") {
            selectItem(activeIndex);
            return true;
          }
          return false;
        },
      });
    }
  }, [ref, filteredItems, activeIndex, selectItem]);

  if (filteredItems.length === 0) return null;

  return (
    <div className="slash-menu" ref={containerRef}>
      {filteredItems.map((item, index) => {
        const Icon = item.icon;
        return (
          <button
            key={item.id}
            className={`slash-menu-item${index === activeIndex ? " is-selected" : ""}`}
            onMouseDown={(e) => {
              // Prevent the editor from losing focus before we run the command.
              e.preventDefault();
              selectItem(index);
            }}
            onMouseEnter={() => setSelectedIndex(index)}
            type="button"
          >
            <span className="slash-menu-icon">
              <Icon size={18} />
            </span>
            <span className="slash-menu-text">
              <span className="slash-menu-title">{t(item.titleKey)}</span>
              <span className="slash-menu-desc">{t(item.descKey)}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Suggestion plugin configuration
// ---------------------------------------------------------------------------

/* eslint-disable @typescript-eslint/no-explicit-any */
function createSuggestionConfig(): Omit<SuggestionOptions, "editor"> {
  return {
    char: "/",
    // Return the full list; the React component filters by translated title.
    items: () => COMMANDS,
    // THE FIX: top-level command is what actually executes when the user
    // clicks or presses Enter. TipTap Suggestion calls this with the
    // selected item as `props`. Without this, clicks were no-ops.
    command: ({
      editor,
      range,
      props,
    }: {
      editor: Editor;
      range: Range;
      props: SlashCommandItem;
    }) => {
      // Delete the "/query" text the user typed.
      editor.chain().focus().deleteRange(range).run();
      // Execute the selected block's insertion. We don't have access to
      // the translator here, so the tiny set of commands that need i18n
      // (image URL prompt) look it up from document.documentElement.lang
      // or fall back to English. Since we pass a minimal translator, we
      // inline a simple passthrough that tries next-intl's bundle via
      // window globals if available, else returns the key unchanged.
      const translate = (key: string): string => {
        // Best-effort: next-intl sets messages on the __NEXT_INTL__ hook,
        // but we can't import the hook at module scope. The only key
        // used here is "slash.image.prompt" — fall back to a hardcoded
        // bilingual value.
        if (key === "slash.image.prompt") {
          const lang =
            typeof document !== "undefined"
              ? (document.documentElement.lang || "").toLowerCase()
              : "";
          return lang.startsWith("zh") ? "图片链接:" : "Image URL:";
        }
        return key;
      };
      props.run(editor, translate);
    },
    render: () => {
      let component: ReactRenderer<CommandListRef> | null = null;
      let popup: TippyInstance[] | null = null;

      return {
        onStart: (props: any) => {
          component = new ReactRenderer(CommandListComponent as any, {
            props,
            editor: props.editor as Editor,
          });

          if (!props.clientRect) return;

          popup = tippy("body", {
            getReferenceClientRect: props.clientRect as () => DOMRect,
            appendTo: () => document.body,
            content: component.element,
            showOnCreate: true,
            interactive: true,
            trigger: "manual",
            placement: "bottom-start",
          });
        },
        onUpdate: (props: any) => {
          component?.updateProps(props);
          if (popup?.[0] && props.clientRect) {
            popup[0].setProps({
              getReferenceClientRect: props.clientRect as () => DOMRect,
            });
          }
        },
        onKeyDown: (props: any) => {
          if (props.event.key === "Escape") {
            popup?.[0]?.hide();
            return true;
          }
          return (component?.ref as CommandListRef | null)?.onKeyDown(props) ?? false;
        },
        onExit: () => {
          popup?.[0]?.destroy();
          component?.destroy();
        },
      };
    },
  };
}
/* eslint-enable @typescript-eslint/no-explicit-any */

// ---------------------------------------------------------------------------
// TipTap Extension
// ---------------------------------------------------------------------------

const SlashCommand = Extension.create({
  name: "slashCommand",

  addOptions() {
    return {
      suggestion: createSuggestionConfig(),
    };
  },

  addProseMirrorPlugins() {
    return [
      Suggestion({
        editor: this.editor,
        ...this.options.suggestion,
      }),
    ];
  },
});

export default SlashCommand;
