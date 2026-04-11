import assert from "node:assert/strict";
import test from "node:test";

import {
  normalizeStreamingMarkdown,
  protectPartialFenceBlocks,
} from "../components/console/chat-markdown-normalization";

test("normalizeStreamingMarkdown normalizes CRLF line endings", () => {
  const normalized = normalizeStreamingMarkdown("第一行\r\n第二行\r第三行");
  assert.equal(normalized, "第一行\n第二行\n第三行");
});

test("normalizeStreamingMarkdown leaves well-formed markdown untouched", () => {
  const source = "## 标题\n\n- 项目一\n- 项目二";
  assert.equal(normalizeStreamingMarkdown(source), source);
});

test("normalizeStreamingMarkdown preserves code block content", () => {
  const source =
    "前文\n\n```python\ndef foo():\n    return 42\n```\n\n后文";
  assert.equal(normalizeStreamingMarkdown(source), source);
});

test("normalizeStreamingMarkdown repairs dangling list markers", () => {
  const source = "- 第一项\n- **\n- 第二项";
  const expected = "- 第一项\n- 第二项";
  assert.equal(normalizeStreamingMarkdown(source), expected);
});

test("normalizeStreamingMarkdown merges punctuation-leading list items", () => {
  const source = "- 新仪式感\n- 。";
  const expected = "- 新仪式感。";
  assert.equal(normalizeStreamingMarkdown(source), expected);
});

test("normalizeStreamingMarkdown strips dangling star from list items", () => {
  const source = "- *bold text continues";
  const expected = "- bold text continues";
  assert.equal(normalizeStreamingMarkdown(source), expected);
});

test("normalizeStreamingMarkdown protects unclosed fence blocks during streaming", () => {
  const source = "前文\n\n```python\ndef foo():\n    return 42";
  assert.equal(normalizeStreamingMarkdown(source), source);
});

test("normalizeStreamingMarkdown isolates glued closing fence from following content", () => {
  const source = "text\n```python\nprint(1)```| table |";
  const result = normalizeStreamingMarkdown(source);
  // Closing ``` must be on its own line for CommonMark
  assert.ok(result.includes("print(1)\n```"), "closing fence should be on its own line");
  assert.ok(result.includes("```\n| table |"), "content after fence should start on new line");
});

test("protectPartialFenceBlocks normalizes CRLF", () => {
  const source = "line1\r\nline2\rline3";
  assert.equal(protectPartialFenceBlocks(source), "line1\nline2\nline3");
});

test("protectPartialFenceBlocks passes through content unchanged", () => {
  const source = "## 标题\n\n- 项目一\n- 项目二\n\n```python\nprint(1)\n```";
  assert.equal(protectPartialFenceBlocks(source), source);
});
