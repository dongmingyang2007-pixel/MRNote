from __future__ import annotations

import re
from typing import Any

from app.core.config import settings


VOICE_RESPONSE_INSTRUCTION_MARKER = "语音回复约束："
_SENTENCE_END_CHARS = "。！？!?；;…."
_TRAILING_CLAUSE_CHARS = "，,、：:；; "
_SENTENCE_CLOSER_CHARS = "\"'”’）】》)]}"
_OPENING_WRAPPER_CHARS = "\"'“‘（【《([{"
_MARKDOWN_LINE_PREFIX_RE = re.compile(r"(?m)^\s*(?:#{1,6}\s+|[-*•]\s+|\d+[.)]\s+)")
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
_WHITESPACE_RE = re.compile(r"\s+")


def build_voice_response_instruction(
    *,
    max_sentences: int | None = None,
    soft_char_limit: int | None = None,
    hard_char_limit: int | None = None,
) -> str:
    resolved_max_sentences = max(1, max_sentences or settings.voice_reply_max_sentences)
    resolved_soft_char_limit = max(1, soft_char_limit or settings.voice_reply_soft_char_limit)
    resolved_hard_char_limit = max(
        resolved_soft_char_limit,
        hard_char_limit or settings.voice_reply_hard_char_limit,
    )
    return (
        f"{VOICE_RESPONSE_INSTRUCTION_MARKER}"
        "请使用自然口语直接回答，不要使用标题、列表、Markdown 或大段铺垫。"
        f"默认只用 1 到 {resolved_max_sentences} 句，先给结论，再补最必要的信息。"
        f"尽量控制在 {resolved_soft_char_limit} 个字以内，绝不超过 {resolved_hard_char_limit} 个字。"
        "如果内容较复杂，先给简短摘要，再询问用户是否需要继续展开。"
    )


def append_voice_response_instruction(system_prompt: str) -> str:
    normalized_prompt = str(system_prompt or "").strip()
    if VOICE_RESPONSE_INSTRUCTION_MARKER in normalized_prompt:
        return normalized_prompt
    instruction = build_voice_response_instruction()
    if not normalized_prompt:
        return instruction
    return f"{normalized_prompt}\n\n{instruction}"


def apply_voice_response_guidance(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    guided_messages = [dict(message) for message in messages]
    for message in guided_messages:
        if str(message.get("role") or "").lower() != "system":
            continue
        content = message.get("content")
        if isinstance(content, str):
            message["content"] = append_voice_response_instruction(content)
            return guided_messages
    guided_messages.insert(
        0,
        {
            "role": "system",
            "content": build_voice_response_instruction(),
        },
    )
    return guided_messages


def normalize_voice_response_text(text: str) -> str:
    normalized = str(text or "").replace("\r", "\n").strip()
    if not normalized:
        return ""
    normalized = normalized.replace("```", "")
    normalized = _MARKDOWN_LINE_PREFIX_RE.sub("", normalized)
    normalized = _INLINE_CODE_RE.sub(r"\1", normalized)
    normalized = normalized.replace("\n", " ")
    normalized = _WHITESPACE_RE.sub(" ", normalized)
    return normalized.strip()


def split_voice_response_sentences(text: str) -> list[str]:
    normalized = normalize_voice_response_text(text)
    if not normalized:
        return []
    sentences: list[str] = []
    start = 0
    index = 0

    while index < len(normalized):
        if _is_sentence_boundary(normalized, index):
            end = index + 1
            while end < len(normalized) and normalized[end] in (_SENTENCE_END_CHARS + _SENTENCE_CLOSER_CHARS):
                end += 1
            sentence = normalized[start:end].strip()
            if sentence:
                sentences.append(sentence)
            start = end
            while start < len(normalized) and normalized[start].isspace():
                start += 1
            index = start
            continue
        index += 1

    tail = normalized[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences or [normalized]


def _merge_voice_parts(parts: list[str]) -> str:
    merged = ""
    for part in parts:
        segment = str(part or "").strip()
        if not segment:
            continue
        if merged and _should_insert_space_between(merged, segment):
            merged = f"{merged} {segment}"
        else:
            merged = f"{merged}{segment}"
    return merged.strip()


def _looks_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _is_sentence_boundary(text: str, index: int) -> bool:
    char = text[index]
    if char in "。！？!?；;…":
        return True
    if char != ".":
        return False

    prev_char = text[index - 1] if index > 0 else ""
    next_char = text[index + 1] if index + 1 < len(text) else ""
    if prev_char.isdigit() and next_char.isdigit():
        return False
    if next_char and not next_char.isspace() and next_char not in _SENTENCE_CLOSER_CHARS:
        return False
    return True


def _should_insert_space_between(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left[-1].isspace() or right[0].isspace():
        return False
    if _looks_cjk(left[-8:]) or _looks_cjk(right[:8]):
        return False
    if not re.search(r"[A-Za-z0-9.!?;:)]$", left.rstrip(_SENTENCE_CLOSER_CHARS)):
        return False
    if not re.match(rf"[A-Za-z0-9{re.escape(_OPENING_WRAPPER_CHARS)}]", right):
        return False
    return True


def _split_trailing_closers(text: str) -> tuple[str, str]:
    end = len(text)
    while end > 0 and text[end - 1] in _SENTENCE_CLOSER_CHARS:
        end -= 1
    return text[:end], text[end:]


def _has_terminal_sentence_punctuation(text: str) -> bool:
    body, _closers = _split_trailing_closers(text.strip())
    return bool(body and body[-1] in _SENTENCE_END_CHARS)


def _ensure_terminal_sentence_punctuation(text: str) -> str:
    trimmed = str(text or "").strip()
    if not trimmed or _has_terminal_sentence_punctuation(trimmed):
        return trimmed

    body, closers = _split_trailing_closers(trimmed)
    if not body:
        return trimmed
    punctuation = "。" if _looks_cjk(body) else "."
    return f"{body}{punctuation}{closers}"


def _trim_voice_segment(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text.strip()

    search_start = max(limit // 2, 0)
    best_index = -1
    for index, char in enumerate(text[:limit]):
        if index < search_start:
            continue
        if char in _TRAILING_CLAUSE_CHARS or char in _SENTENCE_END_CHARS:
            best_index = index

    trimmed = text[: best_index + 1] if best_index >= 0 else text[:limit]
    trimmed = trimmed.strip().rstrip(_TRAILING_CLAUSE_CHARS)
    if not trimmed:
        trimmed = text[:limit].strip()
    return _ensure_terminal_sentence_punctuation(trimmed)


def clamp_voice_response_text(
    text: str,
    *,
    max_sentences: int | None = None,
    soft_char_limit: int | None = None,
    hard_char_limit: int | None = None,
) -> str:
    normalized = normalize_voice_response_text(text)
    if not normalized:
        return ""

    resolved_max_sentences = max(1, max_sentences or settings.voice_reply_max_sentences)
    resolved_soft_char_limit = max(1, soft_char_limit or settings.voice_reply_soft_char_limit)
    resolved_hard_char_limit = max(
        resolved_soft_char_limit,
        hard_char_limit or settings.voice_reply_hard_char_limit,
    )

    sentences = split_voice_response_sentences(normalized)
    selected: list[str] = []

    for sentence in sentences:
        if len(selected) >= resolved_max_sentences:
            break
        if not selected:
            if len(sentence) > resolved_hard_char_limit:
                return _trim_voice_segment(sentence, resolved_hard_char_limit)
            selected.append(sentence)
            continue

        candidate = _merge_voice_parts([*selected, sentence])
        if len(candidate) > resolved_soft_char_limit or len(candidate) > resolved_hard_char_limit:
            break
        selected.append(sentence)

    if not selected:
        selected = [sentences[0]]

    result = _merge_voice_parts(selected)
    if len(result) > resolved_hard_char_limit:
        return _trim_voice_segment(result, resolved_hard_char_limit)

    if len(selected) < len(sentences):
        result = result.rstrip(_TRAILING_CLAUSE_CHARS)
        result = _ensure_terminal_sentence_punctuation(result)
    return result


def voice_response_limit_reached(
    text: str,
    *,
    max_sentences: int | None = None,
    soft_char_limit: int | None = None,
    hard_char_limit: int | None = None,
) -> bool:
    normalized = normalize_voice_response_text(text)
    if not normalized:
        return False
    return clamp_voice_response_text(
        normalized,
        max_sentences=max_sentences,
        soft_char_limit=soft_char_limit,
        hard_char_limit=hard_char_limit,
    ) != normalized
