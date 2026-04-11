#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request


@dataclass
class BenchmarkCase:
    name: str
    query: str
    expected_memory_ids: list[str]
    expected_result_types: list[str]
    require_trace_fields: list[str]
    top_k: int


def _load_fixture(path: Path) -> tuple[str, list[BenchmarkCase]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    project_id = str(payload.get("project_id") or "").strip()
    if not project_id:
        raise ValueError("fixture must include project_id")
    cases: list[BenchmarkCase] = []
    for raw in payload.get("cases", []):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("query") or "").strip()
        query_text = str(raw.get("query") or "").strip()
        if not name or not query_text:
            continue
        cases.append(
            BenchmarkCase(
                name=name,
                query=query_text,
                expected_memory_ids=[
                    str(item).strip()
                    for item in raw.get("expected_memory_ids", [])
                    if isinstance(item, str) and str(item).strip()
                ],
                expected_result_types=[
                    str(item).strip()
                    for item in raw.get("expected_result_types", [])
                    if isinstance(item, str) and str(item).strip()
                ],
                require_trace_fields=[
                    str(item).strip()
                    for item in raw.get("require_trace_fields", [])
                    if isinstance(item, str) and str(item).strip()
                ],
                top_k=max(1, int(raw.get("top_k") or 10)),
            )
        )
    if not cases:
        raise ValueError("fixture must include at least one case")
    return project_id, cases


def _post_json(
    *,
    url: str,
    payload: dict[str, Any],
    workspace_id: str | None,
    cookie: str | None,
    csrf_token: str | None,
) -> Any:
    headers = {"content-type": "application/json"}
    if workspace_id:
        headers["x-workspace-id"] = workspace_id
    if cookie:
        headers["cookie"] = cookie
    if csrf_token:
        headers["x-csrf-token"] = csrf_token
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{url} -> {exc.code}: {body}") from exc


def _hit_memory_ids(hits: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for hit in hits:
        memory = hit.get("memory")
        if isinstance(memory, dict):
            memory_id = str(memory.get("id") or "").strip()
            if memory_id:
                ids.append(memory_id)
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Memory V3 benchmark cases against the live API.")
    parser.add_argument("--fixture", required=True, help="Path to a benchmark fixture JSON file.")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000", help="API base URL.")
    parser.add_argument("--workspace-id", default=None, help="Workspace header to send.")
    parser.add_argument("--cookie", default=None, help="Cookie header for authenticated requests.")
    parser.add_argument("--csrf-token", default=None, help="CSRF token for POST requests.")
    args = parser.parse_args()

    project_id, cases = _load_fixture(Path(args.fixture))
    results: list[dict[str, Any]] = []
    passed = 0

    for case in cases:
        search_payload = {
            "project_id": project_id,
            "query": case.query,
            "top_k": case.top_k,
        }
        search_hits = _post_json(
            url=f"{args.api_base_url}/api/v1/memory/search",
            payload=search_payload,
            workspace_id=args.workspace_id,
            cookie=args.cookie,
            csrf_token=args.csrf_token,
        )
        explain_payload = {**search_payload, "include_subgraph": True}
        explain_body = _post_json(
            url=f"{args.api_base_url}/api/v1/memory/search/explain",
            payload=explain_payload,
            workspace_id=args.workspace_id,
            cookie=args.cookie,
            csrf_token=args.csrf_token,
        )

        hit_memory_ids = _hit_memory_ids(search_hits if isinstance(search_hits, list) else [])
        hit_result_types = {
            str(hit.get("result_type") or "").strip()
            for hit in (search_hits if isinstance(search_hits, list) else [])
            if isinstance(hit, dict)
        }
        trace = explain_body.get("trace") if isinstance(explain_body, dict) else {}
        trace = trace if isinstance(trace, dict) else {}
        expected_hit = not case.expected_memory_ids or any(
            memory_id in hit_memory_ids for memory_id in case.expected_memory_ids
        )
        expected_types = not case.expected_result_types or all(
            result_type in hit_result_types for result_type in case.expected_result_types
        )
        trace_ok = all(trace.get(field) is not None for field in case.require_trace_fields)
        case_passed = expected_hit and expected_types and trace_ok
        if case_passed:
            passed += 1
        results.append(
            {
                "name": case.name,
                "passed": case_passed,
                "query": case.query,
                "hit_memory_ids": hit_memory_ids,
                "hit_result_types": sorted(hit_result_types),
                "trace_keys": sorted(trace.keys()),
                "missing_trace_fields": [
                    field for field in case.require_trace_fields if trace.get(field) is None
                ],
            }
        )

    summary = {
        "project_id": project_id,
        "cases": len(cases),
        "passed": passed,
        "failed": len(cases) - passed,
        "pass_rate": round(passed / max(len(cases), 1), 4),
        "results": results,
    }
    json.dump(summary, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
