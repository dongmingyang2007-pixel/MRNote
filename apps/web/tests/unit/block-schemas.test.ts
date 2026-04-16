import { describe, expect, it } from "vitest";
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import FileBlock from "@/components/console/editor/extensions/FileBlock";

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
