import { describe, expect, it } from "vitest";
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import FileBlock from "@/components/console/editor/extensions/FileBlock";
import AIOutputBlock from "@/components/console/editor/extensions/AIOutputBlock";

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
