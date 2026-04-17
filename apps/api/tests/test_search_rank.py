# ruff: noqa: E402
from app.services.search_rank import rrf_merge


def test_single_list_passthrough() -> None:
    lst = [{"id": "a", "score": 0.9}, {"id": "b", "score": 0.8}]
    out = rrf_merge(lst, limit=10)
    assert [h["id"] for h in out] == ["a", "b"]
    assert out[0]["fused_score"] > out[1]["fused_score"]


def test_two_lists_merge_boosts_common_items() -> None:
    lex = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    sem = [{"id": "b"}, {"id": "a"}, {"id": "d"}]
    out = rrf_merge(lex, sem, limit=10)
    ids = [h["id"] for h in out]
    assert set(ids[:2]) == {"a", "b"}
    assert "c" in ids
    assert "d" in ids


def test_limit_truncates() -> None:
    lst = [{"id": str(i)} for i in range(30)]
    out = rrf_merge(lst, limit=5)
    assert len(out) == 5
    assert [h["id"] for h in out] == ["0", "1", "2", "3", "4"]


def test_empty_lists_return_empty() -> None:
    assert rrf_merge([], [], limit=10) == []
    assert rrf_merge(limit=10) == []
