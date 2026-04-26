import type { Editor, Range } from "@tiptap/core";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createSuggestionConfig } from "@/components/console/editor/SlashCommandMenu";

describe("SlashCommandMenu", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("formats Study Q&A placeholder with the prompted question", () => {
    const translate = vi.fn(
      (key: string, values?: Record<string, string | number | Date>) => {
        if (key === "slash.studyQa.prompt") return "Question?";
        if (key === "slash.studyQa.placeholder") {
          if (!values?.question) {
            throw new Error("missing question");
          }
          return `**Study Q&A**\n\n> Question: ${values.question}`;
        }
        return key;
      },
    );
    const insertContent = vi.fn();
    const chain = {
      focus: vi.fn(() => chain),
      deleteRange: vi.fn(() => chain),
      insertContent: vi.fn((content: unknown) => {
        insertContent(content);
        return chain;
      }),
      run: vi.fn(() => true),
    };
    const editor = {
      chain: vi.fn(() => chain),
    } as unknown as Editor;
    const promptSpy = vi
      .spyOn(window, "prompt")
      .mockReturnValue("What is retrieval practice?");
    const dispatchSpy = vi
      .spyOn(window, "dispatchEvent")
      .mockImplementation(() => true);
    const suggestion = createSuggestionConfig(translate);
    const studyQa = (suggestion.items as () => Array<{ id: string }>)().find(
      (item) => item.id === "studyQa",
    );

    expect(studyQa).toBeTruthy();
    suggestion.command?.({
      editor,
      range: { from: 1, to: 2 } as Range,
      props: studyQa,
    });

    expect(promptSpy).toHaveBeenCalledWith("Question?");
    expect(translate).toHaveBeenCalledWith("slash.studyQa.placeholder", {
      question: "What is retrieval practice?",
    });
    expect(insertContent).toHaveBeenCalledWith({
      type: "ai_output",
      attrs: {
        content_markdown:
          "**Study Q&A**\n\n> Question: What is retrieval practice?",
        action_type: "study_qa",
        action_log_id: "",
      },
    });
    expect(dispatchSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "mrai:open-ai-panel",
        detail: {
          tab: "study",
          prefill: "What is retrieval practice?",
        },
      }),
    );
  });
});
