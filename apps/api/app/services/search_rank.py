"""Reciprocal Rank Fusion for merging lexical + semantic search results.

Standard RRF: fused_score(item) = sum over ranks of 1 / (k + rank).
Items are keyed by their `id` field unless a custom key_fn is provided.
"""

from __future__ import annotations

from typing import Any, Callable


def rrf_merge(
    *rank_lists: list[dict[str, Any]],
    k: int = 60,
    limit: int = 20,
    key_fn: Callable[[dict[str, Any]], str] | None = None,
) -> list[dict[str, Any]]:
    """Merge multiple ranked result lists via Reciprocal Rank Fusion.

    Returns a new list of hits ordered by fused_score desc, truncated
    to `limit`. Each returned hit has `fused_score` set; all other keys
    are preserved from the first list the hit appeared in.
    """
    if not rank_lists:
        return []
    resolve_key = key_fn or (lambda h: str(h.get("id", "")))
    fused: dict[str, dict[str, Any]] = {}
    for lst in rank_lists:
        for rank, hit in enumerate(lst, start=1):
            key = resolve_key(hit)
            if not key:
                continue
            contribution = 1.0 / (k + rank)
            if key in fused:
                fused[key]["fused_score"] += contribution
            else:
                new_hit = dict(hit)
                new_hit["fused_score"] = contribution
                fused[key] = new_hit
    ordered = sorted(fused.values(), key=lambda h: h["fused_score"], reverse=True)
    return ordered[:limit]
