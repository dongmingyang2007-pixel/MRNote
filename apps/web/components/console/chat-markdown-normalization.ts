// Minimal client-side markdown helpers.
//
// Heavy normalization lives in the backend (assistant_markdown.py).
// The frontend only needs two things:
//   1. normalizeStreamingMarkdown  – repair streaming-specific artefacts
//      (fragmented list items) that appear before the backend finalises.
//   2. protectPartialFenceBlocks   – keep partially-revealed text (animation)
//      from breaking react-markdown by leaving unclosed fences untouched.

const FENCE_BLOCK_PATTERN = /(```[\s\S]*?```)/g;
const FENCE_BLOCK_EXACT_PATTERN = /^```[\s\S]*?```$/;

/* ------------------------------------------------------------------ */
/*  repairFragmentedListItems – streaming artefact fixer               */
/* ------------------------------------------------------------------ */

const LONE_MARKER_LIST_ITEM = /^[ \t]*[-*+][ \t]+\*{1,3}[ \t]*$/;
const LIST_ITEM_PREFIX = /^([ \t]*[-*+][ \t]+|[ \t]*\d+[.)]\s*)/;
const LIST_COLON_CONTINUATION = /^([ \t]*[-*+][ \t]+)[：:](.*)$/;
const LIST_ITEM_DANGLING_STAR = /^([ \t]*[-*+][ \t]+)\*([^*].*)/;
const LIST_ITEM_CONTENT = /^[ \t]*[-*+][ \t]+(.+)/;
const LIST_PUNCTUATION_FRAGMENT =
  /^[ \t]*[-*+][ \t]+([，。、；！？）)」』】"'：:][^\S\n]*)(.*)$/;
const LIST_CONTINUATION_CONTENT =
  /^[ \t]*[-*+][ \t]+(的|地|得|是|在|把|被|让|像|用|从|向|对|给|跟|和|与|及|并|而|但|也|又|还|都|就|才|再|更|最|太|很|超|可|能|会|要|想|有|没|不)/;
const LIST_ITEM_SENTENCE_END = /[。！？.!?]["'」』】）)"]?\s*$/;
const LIST_ITEM_SHORT_PHRASE = /^[ \t]*[-*+][ \t]+\S{1,6}\s*$/;
const LIST_ITEM_INCOMPLETE_SUFFIX =
  /(?:的|地|得|着|了|和|与|及|并|而|但|从|向|对|给|为|在)\s*$/;
const LIST_INDENT = /^([ \t]*)/;

function extractListItemContent(line: string): string | null {
  const match = line.match(LIST_ITEM_CONTENT);
  return match ? match[1].trim() : null;
}

function getIndentLevel(line: string): number {
  const match = line.match(LIST_INDENT);
  return match ? match[1].length : 0;
}

function repairFragmentedListItems(lines: string[]): string[] {
  if (!lines.length) return lines;

  const repaired: string[] = [];
  for (const line of lines) {
    // 1. Remove standalone dangling marker list items: `- *`, `- **`
    if (LONE_MARKER_LIST_ITEM.test(line)) continue;

    const prevIdx = repaired.length - 1;
    const hasPrev = prevIdx >= 0 && LIST_ITEM_PREFIX.test(repaired[prevIdx]);
    const sameIndent =
      hasPrev && getIndentLevel(line) === getIndentLevel(repaired[prevIdx]);
    const canMerge = hasPrev && sameIndent;

    // 2. Merge punctuation-leading list items: `- 。` → append to previous
    if (canMerge) {
      const punctMatch = line.match(LIST_PUNCTUATION_FRAGMENT);
      if (punctMatch) {
        const prev = repaired[prevIdx].trimEnd();
        const p = punctMatch[1].trim();
        const rest = (punctMatch[2] ?? "").trim();
        repaired[prevIdx] = rest ? `${prev}${p}${rest}` : `${prev}${p}`;
        continue;
      }
    }

    // 3. Merge `- ：text` colon continuation into previous
    if (canMerge) {
      const colonMatch = line.match(LIST_COLON_CONTINUATION);
      if (colonMatch) {
        const prev = repaired[prevIdx].trimEnd();
        const colon = line.match(/[：:]/)?.[0] ?? "：";
        const rest = colonMatch[2].trim();
        repaired[prevIdx] = rest ? `${prev}${colon}${rest}` : `${prev}${colon}`;
        continue;
      }
    }

    // 4. Merge continuation-token list items into previous
    if (
      canMerge &&
      LIST_CONTINUATION_CONTENT.test(line) &&
      !LIST_ITEM_SENTENCE_END.test(repaired[prevIdx])
    ) {
      const content = extractListItemContent(line);
      if (content) {
        repaired[prevIdx] = `${repaired[prevIdx].trimEnd()}${content}`;
        continue;
      }
    }

    // 5. Merge very short phrases (<=6 chars) into previous only when
    //    previous item ends with an incomplete suffix (的/地/得/着/了...)
    if (
      canMerge &&
      LIST_ITEM_SHORT_PHRASE.test(line) &&
      !LIST_ITEM_SENTENCE_END.test(repaired[prevIdx]) &&
      LIST_ITEM_INCOMPLETE_SUFFIX.test(repaired[prevIdx])
    ) {
      const content = extractListItemContent(line);
      if (content) {
        repaired[prevIdx] = `${repaired[prevIdx].trimEnd()}${content}`;
        continue;
      }
    }

    // 6. Strip leading dangling `*` from list items: `- *text` → `- text`
    const starMatch = line.match(LIST_ITEM_DANGLING_STAR);
    if (starMatch) {
      repaired.push(`${starMatch[1]}${starMatch[2]}`);
      continue;
    }

    repaired.push(line);
  }

  return repaired;
}

/* ------------------------------------------------------------------ */
/*  Exported helpers                                                    */
/* ------------------------------------------------------------------ */

/**
 * Lightweight normalisation for in-flight streaming content.
 *
 * Repairs fragmented list items that appear while the LLM is still
 * emitting tokens.  Does NOT duplicate the heavy merge / heading /
 * table / math normalisation that the backend already handles.
 */
/**
 * Ensure the closing ``` in a matched fence block sits on its own line.
 * CommonMark requires this; LLMs sometimes glue the fence to code.
 */
function isolateFenceMarkers(block: string): string {
  const firstNl = block.indexOf("\n");
  if (firstNl < 0) {
    return block.slice(0, 3) + "\n" + block.slice(3, -3) + "\n```";
  }
  const opening = block.slice(0, firstNl + 1);
  const rest = block.slice(firstNl + 1);
  const closeIdx = rest.lastIndexOf("```");
  if (closeIdx < 0) return block;
  let beforeClose = rest.slice(0, closeIdx);
  const closingAndAfter = rest.slice(closeIdx);
  if (beforeClose && !beforeClose.endsWith("\n")) {
    beforeClose += "\n";
  }
  return opening + beforeClose + closingAndAfter;
}

export function normalizeStreamingMarkdown(text: string): string {
  const raw = text.replace(/\r\n?/g, "\n");
  if (!raw.trim()) return raw;

  const parts = raw.split(FENCE_BLOCK_PATTERN);
  const result: string[] = [];

  for (let i = 0; i < parts.length; i++) {
    const part = parts[i];
    if (FENCE_BLOCK_EXACT_PATTERN.test(part)) {
      // Ensure fence markers are CommonMark-compliant
      const isolated = isolateFenceMarkers(part);
      // Ensure newline before opening fence
      if (result.length > 0) {
        const prev = result[result.length - 1];
        if (prev && !prev.endsWith("\n")) {
          result[result.length - 1] = prev + "\n";
        }
      }
      result.push(isolated);
      // Ensure newline after closing fence
      if (i + 1 < parts.length && parts[i + 1] && !parts[i + 1].startsWith("\n")) {
        result.push("\n");
      }
      continue;
    }

    // Protect unclosed fence blocks (streaming in progress)
    const unclosedIdx = part.lastIndexOf("```");
    if (unclosedIdx >= 0) {
      const before = part.slice(0, unclosedIdx);
      const fenceAndRest = part.slice(unclosedIdx);
      let repaired = before
        ? repairFragmentedListItems(before.split("\n")).join("\n")
        : "";
      // Ensure newline before unclosed opening fence
      if (repaired && !repaired.endsWith("\n")) {
        repaired += "\n";
      }
      result.push(repaired + fenceAndRest);
      continue;
    }

    result.push(repairFragmentedListItems(part.split("\n")).join("\n"));
  }

  return result.join("");
}

/**
 * Fence-block-aware passthrough for the character-reveal animation.
 *
 * During animation visibleText may slice mid-fence-block; this ensures
 * the unclosed fence is left verbatim so react-markdown doesn't choke.
 * No content merging is performed — the full text is already normalised
 * by the backend.
 */
export function protectPartialFenceBlocks(text: string): string {
  return text.replace(/\r\n?/g, "\n");
}
