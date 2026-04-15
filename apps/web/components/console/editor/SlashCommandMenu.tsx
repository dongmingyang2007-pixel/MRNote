"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Extension } from "@tiptap/core";
import { ReactRenderer } from "@tiptap/react";
import Suggestion, { type SuggestionOptions } from "@tiptap/suggestion";
import tippy, { type Instance as TippyInstance } from "tippy.js";
import type { Editor } from "@tiptap/core";
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
} from "lucide-react";

// ---------------------------------------------------------------------------
// Command items
// ---------------------------------------------------------------------------

interface SlashCommandItem {
  title: string;
  description: string;
  icon: React.ElementType;
  command: (editor: Editor) => void;
}

const COMMANDS: SlashCommandItem[] = [
  {
    title: "Heading 1",
    description: "Large section heading",
    icon: Heading1,
    command: (editor) => editor.chain().focus().toggleHeading({ level: 1 }).run(),
  },
  {
    title: "Heading 2",
    description: "Medium section heading",
    icon: Heading2,
    command: (editor) => editor.chain().focus().toggleHeading({ level: 2 }).run(),
  },
  {
    title: "Heading 3",
    description: "Small section heading",
    icon: Heading3,
    command: (editor) => editor.chain().focus().toggleHeading({ level: 3 }).run(),
  },
  {
    title: "Paragraph",
    description: "Plain text block",
    icon: Type,
    command: (editor) => editor.chain().focus().setParagraph().run(),
  },
  {
    title: "Bullet List",
    description: "Unordered list",
    icon: List,
    command: (editor) => editor.chain().focus().toggleBulletList().run(),
  },
  {
    title: "Numbered List",
    description: "Ordered list",
    icon: ListOrdered,
    command: (editor) => editor.chain().focus().toggleOrderedList().run(),
  },
  {
    title: "Task List",
    description: "Checklist with checkboxes",
    icon: CheckSquare,
    command: (editor) => editor.chain().focus().toggleTaskList().run(),
  },
  {
    title: "Code Block",
    description: "Code with syntax highlighting",
    icon: Code,
    command: (editor) => editor.chain().focus().toggleCodeBlock().run(),
  },
  {
    title: "Quote",
    description: "Block quotation",
    icon: Quote,
    command: (editor) => editor.chain().focus().toggleBlockquote().run(),
  },
  {
    title: "Divider",
    description: "Horizontal divider",
    icon: Minus,
    command: (editor) => editor.chain().focus().setHorizontalRule().run(),
  },
  {
    title: "Image",
    description: "Embed an image",
    icon: ImageIcon,
    command: (editor) => {
      const url = window.prompt("Image URL:");
      if (url) {
        editor.chain().focus().setImage({ src: url }).run();
      }
    },
  },
  {
    title: "Math Block",
    description: "LaTeX formula block",
    icon: Sigma,
    command: (editor) => {
      editor
        .chain()
        .focus()
        .insertContent({ type: "mathBlock", attrs: { latex: "" } })
        .run();
    },
  },
  {
    title: "Inline Math",
    description: "Inline LaTeX formula",
    icon: Sigma,
    command: (editor) => {
      editor
        .chain()
        .focus()
        .insertContent({ type: "inlineMath", attrs: { latex: "" } })
        .run();
    },
  },
  {
    title: "Callout",
    description: "Highlighted info block",
    icon: AlertCircle,
    command: (editor) => {
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
    title: "Whiteboard",
    description: "Interactive drawing canvas",
    icon: PenTool,
    command: (editor) => {
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
];

// ---------------------------------------------------------------------------
// Command List Component (rendered inside tippy popup)
// ---------------------------------------------------------------------------

interface CommandListProps {
  items: SlashCommandItem[];
  command: (item: SlashCommandItem) => void;
}

interface CommandListRef {
  onKeyDown: (props: { event: KeyboardEvent }) => boolean;
}

const CommandListComponent = ({
  items,
  command,
  ref,
}: CommandListProps & { ref: React.Ref<CommandListRef> }) => {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const activeIndex = items.length === 0 ? 0 : Math.min(selectedIndex, items.length - 1);

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
      const item = items[index];
      if (item) command(item);
    },
    [items, command],
  );

  // Expose keyboard handler to tippy
  useEffect(() => {
    if (typeof ref === "function") {
      ref({
        onKeyDown: ({ event }: { event: KeyboardEvent }) => {
          if (event.key === "ArrowUp") {
            if (items.length === 0) {
              return true;
            }
            setSelectedIndex((i) => (i + items.length - 1) % items.length);
            return true;
          }
          if (event.key === "ArrowDown") {
            if (items.length === 0) {
              return true;
            }
            setSelectedIndex((i) => (i + 1) % items.length);
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
  }, [ref, items, activeIndex, selectItem]);

  if (items.length === 0) return null;

  return (
    <div className="slash-menu" ref={containerRef}>
      {items.map((item, index) => {
        const Icon = item.icon;
        return (
          <button
            key={item.title}
            className={`slash-menu-item${index === activeIndex ? " is-selected" : ""}`}
            onClick={() => selectItem(index)}
            onMouseEnter={() => setSelectedIndex(index)}
            type="button"
          >
            <span className="slash-menu-icon">
              <Icon size={18} />
            </span>
            <span className="slash-menu-text">
              <span className="slash-menu-title">{item.title}</span>
              <span className="slash-menu-desc">{item.description}</span>
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
    items: ({ query }: { query: string }) => {
      return COMMANDS.filter((item) =>
        item.title.toLowerCase().includes(query.toLowerCase()),
      );
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
