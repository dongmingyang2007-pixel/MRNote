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
  Lightbulb,
  BookOpen,
} from "lucide-react";
import { apiPost, isApiRequestError } from "@/lib/api";

// ---------------------------------------------------------------------------
// Command item metadata (i18n keys on console-notebooks namespace)
// ---------------------------------------------------------------------------

interface SlashCommandContext {
  /** Optional accessor for the active page id. Commands that call page-scoped
   * endpoints (AI brainstorm / study Q&A) need this to scope their request.
   * The suggestion plugin is instantiated outside of the React tree so we can't
   * rely on PageIdContext — NoteEditor wires it in via `createSuggestionConfig`. */
  getPageId?: () => string | null;
}

interface SlashCommandItem {
  id: string;
  titleKey: string;
  descKey: string;
  icon: React.ElementType;
  /** When invoked, the TipTap range is already deleted. Use the editor
   * chain to insert the desired block. The translator is passed so
   * commands that need localized prompts (e.g. image URL) can use it.
   * `ctx` carries host-provided helpers like the current page id. */
  run: (editor: Editor, t: (key: string) => string, ctx?: SlashCommandContext) => void;
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
      // U-25 — replace the lo-fi window.prompt with a native file picker.
      // We embed the selected image as a data URL so it works without
      // touching the attachment upload API (which requires a React-context
      // page id that isn't reachable from here). Users that want to embed
      // a remote URL can still fall back to the prompt via Cancel→prompt.
      if (typeof window === "undefined") return;
      const input = document.createElement("input");
      input.type = "file";
      input.accept = "image/*";
      input.style.display = "none";
      input.addEventListener("change", () => {
        const file = input.files?.[0];
        if (!file) {
          // Fallback: user cancelled → fall through to URL prompt.
          const url = window.prompt(t("slash.image.prompt"));
          if (url) {
            editor.chain().focus().setImage({ src: url }).run();
          }
          input.remove();
          return;
        }
        const reader = new FileReader();
        reader.onload = () => {
          const src = typeof reader.result === "string" ? reader.result : "";
          if (src) {
            editor.chain().focus().setImage({ src }).run();
          }
          input.remove();
        };
        reader.onerror = () => {
          input.remove();
        };
        reader.readAsDataURL(file);
      });
      document.body.appendChild(input);
      input.click();
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
  {
    // Spec §19.1 — "AI brainstorm" block. Calls POST
    // /api/v1/ai/notebook/brainstorm with the user-supplied topic and
    // inlines the returned Markdown bullet list as a filled-in ai_output
    // node (action_type = "brainstorm") so the result is editable / linkable
    // alongside the rest of the page.
    id: "aiBrainstorm",
    titleKey: "slash.aiBrainstorm.title",
    descKey: "slash.aiBrainstorm.desc",
    icon: Lightbulb,
    run: (editor, t, ctx) => {
      if (typeof window === "undefined") return;
      const topic = (window.prompt(t("slash.aiBrainstorm.prompt")) || "").trim();
      if (!topic) return;

      // Insert a placeholder ai_output block immediately so the user sees
      // something happen. We'll overwrite it once the request returns.
      const placeholderText = t("slash.aiBrainstorm.loading");
      editor
        .chain()
        .focus()
        .insertContent({
          type: "ai_output",
          attrs: {
            content_markdown: placeholderText,
            action_type: "brainstorm",
            action_log_id: "",
          },
        })
        .run();

      const pageId = ctx?.getPageId?.() || null;
      const body: Record<string, unknown> = { topic };
      if (pageId) body.page_id = pageId;

      void (async () => {
        try {
          const resp = await apiPost<{
            markdown: string;
            topic: string;
            count: number;
          }>("/api/v1/ai/notebook/brainstorm", body);
          const markdown = resp?.markdown || "";
          // Replace the last inserted node (the placeholder we just added) with
          // the filled-in result. Walk the document and update the most recent
          // ai_output node whose content_markdown matches the placeholder text.
          const { state } = editor;
          const tr = state.tr;
          let replaced = false;
          state.doc.descendants((node, pos) => {
            if (replaced) return false;
            if (
              node.type.name === "ai_output" &&
              node.attrs?.content_markdown === placeholderText &&
              node.attrs?.action_type === "brainstorm"
            ) {
              tr.setNodeMarkup(pos, undefined, {
                ...node.attrs,
                content_markdown: markdown,
              });
              replaced = true;
              return false;
            }
            return true;
          });
          if (replaced) editor.view.dispatch(tr);
        } catch (error) {
          const msg = isApiRequestError(error)
            ? error.message || t("slash.aiBrainstorm.error")
            : t("slash.aiBrainstorm.error");
          const { state } = editor;
          const tr = state.tr;
          let replaced = false;
          state.doc.descendants((node, pos) => {
            if (replaced) return false;
            if (
              node.type.name === "ai_output" &&
              node.attrs?.content_markdown === placeholderText &&
              node.attrs?.action_type === "brainstorm"
            ) {
              tr.setNodeMarkup(pos, undefined, {
                ...node.attrs,
                content_markdown: `**${msg}**`,
              });
              replaced = true;
              return false;
            }
            return true;
          });
          if (replaced) editor.view.dispatch(tr);
        }
      })();
    },
  },
  {
    // Spec §19.1 — "Study Q&A" block. Minimal viable version: drop a
    // placeholder ai_output node (action_type = "study_qa") seeded with the
    // user's question and guide them to finish the ask in the right-hand AI
    // Panel Study tab. A full in-slash asset picker is a larger UI and can
    // land once users request it.
    id: "studyQa",
    titleKey: "slash.studyQa.title",
    descKey: "slash.studyQa.desc",
    icon: BookOpen,
    run: (editor, t) => {
      if (typeof window === "undefined") return;
      const question = (window.prompt(t("slash.studyQa.prompt")) || "").trim();
      if (!question) return;

      const body = t("slash.studyQa.placeholder").replace("{question}", question);
      editor
        .chain()
        .focus()
        .insertContent({
          type: "ai_output",
          attrs: {
            content_markdown: body,
            action_type: "study_qa",
            action_log_id: "",
          },
        })
        .run();

      // Fire a best-effort custom event so any listening host (AI panel
      // window) can jump to the Study tab. AIPanelWindow doesn't currently
      // subscribe — the event is harmless if no one listens and makes the
      // upgrade path painless when it does.
      try {
        window.dispatchEvent(
          new CustomEvent("mrai:open-ai-panel", {
            detail: { tab: "study", prefill: question },
          }),
        );
      } catch {
        // non-fatal
      }
    },
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
type Translator = (key: string) => string;

export function createSuggestionConfig(
  translate: Translator,
  options?: SlashCommandContext,
): Omit<SuggestionOptions, "editor"> {
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
      props.run(editor, translate, options);
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
    // Default translator returns the key itself. Callers should configure
    // this extension with a real translator bound to next-intl.
    return {
      suggestion: createSuggestionConfig((k) => k),
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
