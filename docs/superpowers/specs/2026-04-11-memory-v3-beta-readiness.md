# Memory V3 Beta Readiness

## Scope

This pass closes Memory V3 into a single, explainable memory graph service with:

- unified layered `/api/v1/memory/search`
- `/api/v1/memory/search/explain` for trace + suppressed candidates + subgraph
- `/api/v1/memory/{id}/subgraph` for direct graph inspection
- `outcomes / learning-runs / health / playbook feedback`
- nightly memory sleep cycle scheduling
- workbench drill-down from `Learning / Health` into memory detail tabs
- a minimal SDK surface in [memory-sdk.ts](/Users/dog/Desktop/铭润/apps/web/lib/memory-sdk.ts)
- a repeatable benchmark harness in [run_memory_benchmark.py](/Users/dog/Desktop/铭润/scripts/run_memory_benchmark.py)

## Fixed Service Contract

- `MemoryOut` carries `suppression_reason`, `reconfirm_after`, `last_used_at`, `reuse_success_rate`
- `MemoryDetailOut` carries `episodes`, `learning_history`, `views`, `evidences`
- `MemorySearchHit` carries `selection_reason`, `suppression_reason`, `outcome_weight`, `episode_id`
- `MemoryExplainOut` carries `hits`, `trace`, `suppressed_candidates`, `subgraph`

The intended client entrypoints are:

- [memory.py](/Users/dog/Desktop/铭润/apps/api/app/routers/memory.py)
- [memory-sdk.ts](/Users/dog/Desktop/铭润/apps/web/lib/memory-sdk.ts)

## Learning Loop

Learning runs are normalized to the fixed stage order:

1. `observe`
2. `extract`
3. `consolidate`
4. `graphify`
5. `reflect`
6. `reuse`

Backfill and feedback paths now merge onto the same stage ordering instead of writing ad hoc lists.

Nightly sleep cycle is scheduled via:

- [celery_app.py](/Users/dog/Desktop/铭润/apps/api/app/tasks/celery_app.py)
- [worker_tasks.py](/Users/dog/Desktop/铭润/apps/api/app/tasks/worker_tasks.py)

The nightly cycle performs:

- compaction
- graph repair
- subject/profile/timeline/playbook refresh
- health refresh
- reflection backfill for completed learning runs linked to outcomes

## Frontend Drill-down

The memory workbench now preserves a detail tab target in page state. Clicking from:

- `Learning` opens the `learning` tab
- `Health -> high risk playbook` opens the `views` tab
- `Health -> stale/conflict` opens the `timeline` tab
- `Health -> needs reconfirm` opens the `history` tab

Relevant files:

- [page.tsx](/Users/dog/Desktop/铭润/apps/web/app/[locale]/workspace/memory/page.tsx)
- [MemoryDetailPanel.tsx](/Users/dog/Desktop/铭润/apps/web/components/console/memory/MemoryDetailPanel.tsx)
- [MemoryLearningPanel.tsx](/Users/dog/Desktop/铭润/apps/web/components/console/memory/MemoryLearningPanel.tsx)
- [MemoryHealthPanel.tsx](/Users/dog/Desktop/铭润/apps/web/components/console/memory/MemoryHealthPanel.tsx)

## Benchmark Harness

Use the sample fixture:

- [memory_benchmark.sample.json](/Users/dog/Desktop/铭润/scripts/fixtures/memory_benchmark.sample.json)

Run:

```bash
python3 scripts/run_memory_benchmark.py \
  --fixture scripts/fixtures/memory_benchmark.sample.json \
  --api-base-url http://127.0.0.1:8000 \
  --workspace-id <workspace-id> \
  --cookie "auth_state=1; mingrun_workspace_id=<workspace-id>" \
  --csrf-token <csrf-token>
```

The harness checks:

- expected memory hit presence
- expected mixed result types
- required explain-trace fields

It exits non-zero on failure, so it can be used in release gating or CI wrappers.

## Beta Exit Gates

Do not mark Memory V3 Beta ready unless all of these hold:

- explain route returns stable trace fields
- private memory remains invisible through search, health, learning-runs, and feedback paths
- promote/edit/delete keep graph, list, and detail in sync
- sleep cycle runs without mutating memory semantics silently
- benchmark harness passes project-specific acceptance cases
