"use client";

import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

import { protectPartialFenceBlocks } from "../chat-markdown-normalization";

interface Props {
  text: string;
  /** When streaming, render plaintext to avoid half-parsed markdown flashing. */
  streaming?: boolean;
  className?: string;
}

// LLMs frequently emit LaTeX with \(...\) and \[...\] delimiters, but
// remark-math only recognises $...$ / $$...$$ out of the box. Translate the
// escaped-paren/bracket form into dollars before parsing. Lazy matching keeps
// a pair from swallowing other math expressions on the same line.
function normalizeLatexDelimiters(text: string): string {
  return text
    .replace(/\\\[([\s\S]*?)\\\]/g, (_, body) => `\n$$\n${body.trim()}\n$$\n`)
    .replace(/\\\(([\s\S]*?)\\\)/g, (_, body) => `$${body.trim()}$`);
}

/**
 * Shared markdown + LaTeX renderer used by both the chat message list and the
 * floating AI panel. Keep this free of chat-specific concerns so any surface
 * that needs "render an LLM's markdown output" can drop it in.
 */
export default function MarkdownContent({
  text,
  streaming = false,
  className = "chat-markdown",
}: Props) {
  if (streaming) {
    return (
      <div className={className}>
        <div className="chat-streaming-plaintext">{text}</div>
      </div>
    );
  }
  const safe = normalizeLatexDelimiters(protectPartialFenceBlocks(text));
  return (
    <div className={className}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkBreaks, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                color: "var(--console-accent, var(--console-accent, #0D9488))",
                textDecoration: "underline",
              }}
            >
              {children}
            </a>
          ),
        }}
      >
        {safe}
      </ReactMarkdown>
    </div>
  );
}
