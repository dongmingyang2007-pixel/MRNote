import { describe, expect, it } from "vitest";
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import FileBlock from "@/components/console/editor/extensions/FileBlock";
import AIOutputBlock from "@/components/console/editor/extensions/AIOutputBlock";
import ReferenceBlock from "@/components/console/editor/extensions/ReferenceBlock";
import TaskBlock from "@/components/console/editor/extensions/TaskBlock";

function buildEditor(extensions: unknown[]) {
  return new Editor({
    extensions: [StarterKit, ...(extensions as never[])],
    content: "",
  });
}

describe("FileBlock schema", () => {
  it("inserts with expected default attrs", () => {
    const editor = buildEditor([FileBlock]);
    editor
      .chain()
      .focus()
      .insertContent({
        type: "file",
        attrs: {
          attachment_id: "att_1",
          filename: "a.pdf",
          mime_type: "application/pdf",
          size_bytes: 42,
        },
      })
      .run();
    const json = editor.getJSON();
    const fileNode = (json.content ?? []).find((n) => n.type === "file");
    expect(fileNode?.attrs?.attachment_id).toBe("att_1");
    expect(fileNode?.attrs?.filename).toBe("a.pdf");
    expect(fileNode?.attrs?.mime_type).toBe("application/pdf");
    expect(fileNode?.attrs?.size_bytes).toBe(42);
  });

  it("round-trips JSON through setContent", () => {
    const editor = buildEditor([FileBlock]);
    const original = {
      type: "doc",
      content: [
        {
          type: "file",
          attrs: {
            attachment_id: "att_2",
            filename: "x.png",
            mime_type: "image/png",
            size_bytes: 7,
          },
        },
      ],
    };
    editor.commands.setContent(original);
    const roundtripped = editor.getJSON();
    expect(roundtripped.content?.[0].type).toBe("file");
    expect(roundtripped.content?.[0].attrs?.filename).toBe("x.png");
  });
});

describe("AIOutputBlock schema", () => {
  it("inserts with expected default attrs", () => {
    const editor = buildEditor([AIOutputBlock]);
    editor
      .chain()
      .focus()
      .insertContent({
        type: "ai_output",
        attrs: {
          content_markdown: "hello world",
          action_type: "selection.rewrite",
          action_log_id: "log_1",
          model_id: "qwen-plus",
          sources: [{ type: "memory", id: "m1", title: "M" }],
        },
      })
      .run();
    const json = editor.getJSON();
    const node = json.content?.find((n) => n.type === "ai_output");
    expect(node?.attrs?.content_markdown).toBe("hello world");
    expect(node?.attrs?.model_id).toBe("qwen-plus");
    expect((node?.attrs?.sources as { id: string }[] | undefined)?.[0]?.id).toBe("m1");
  });

  it("round-trips JSON through setContent", () => {
    const editor = buildEditor([AIOutputBlock]);
    const original = {
      type: "doc",
      content: [
        {
          type: "ai_output",
          attrs: {
            content_markdown: "rt",
            action_type: "ask",
            action_log_id: "log_2",
            model_id: null,
            sources: [],
          },
        },
      ],
    };
    editor.commands.setContent(original);
    const node = editor.getJSON().content?.[0];
    expect(node?.type).toBe("ai_output");
    expect(node?.attrs?.content_markdown).toBe("rt");
  });
});

describe("ReferenceBlock schema", () => {
  it("inserts with expected default attrs", () => {
    const editor = buildEditor([ReferenceBlock]);
    editor
      .chain()
      .focus()
      .insertContent({
        type: "reference",
        attrs: {
          target_type: "page",
          target_id: "p1",
          title: "Intro page",
          snippet: "short snippet",
        },
      })
      .run();
    const node = editor.getJSON().content?.find((n) => n.type === "reference");
    expect(node?.attrs?.target_type).toBe("page");
    expect(node?.attrs?.target_id).toBe("p1");
  });

  it("round-trips JSON through setContent", () => {
    const editor = buildEditor([ReferenceBlock]);
    editor.commands.setContent({
      type: "doc",
      content: [
        {
          type: "reference",
          attrs: {
            target_type: "memory",
            target_id: "m1",
            title: "Memory A",
            snippet: "",
          },
        },
      ],
    });
    const node = editor.getJSON().content?.[0];
    expect(node?.type).toBe("reference");
    expect(node?.attrs?.target_type).toBe("memory");
  });
});

describe("TaskBlock schema", () => {
  it("inserts with expected default attrs", () => {
    const editor = buildEditor([TaskBlock]);
    editor
      .chain()
      .focus()
      .insertContent({
        type: "task",
        attrs: {
          block_id: "b1",
          title: "do X",
          description: null,
          due_date: null,
          completed: false,
          completed_at: null,
        },
      })
      .run();
    const node = editor.getJSON().content?.find((n) => n.type === "task");
    expect(node?.attrs?.block_id).toBe("b1");
    expect(node?.attrs?.completed).toBe(false);
  });

  it("round-trips JSON through setContent", () => {
    const editor = buildEditor([TaskBlock]);
    editor.commands.setContent({
      type: "doc",
      content: [
        {
          type: "task",
          attrs: {
            block_id: "b2",
            title: "rt",
            description: "desc",
            due_date: "2026-05-01",
            completed: true,
            completed_at: "2026-04-16T00:00:00Z",
          },
        },
      ],
    });
    const node = editor.getJSON().content?.[0];
    expect(node?.type).toBe("task");
    expect(node?.attrs?.completed).toBe(true);
    expect(node?.attrs?.due_date).toBe("2026-05-01");
  });
});
