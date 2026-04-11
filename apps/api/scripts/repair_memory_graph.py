#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys

from app.db.session import SessionLocal
from app.models import Project
from app.services.memory_graph_repair import repair_project_memory_graph


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair auto-generated memory graph structure for one project.")
    parser.add_argument("--workspace-id", required=True, help="Workspace id that owns the project.")
    parser.add_argument("--project-id", required=True, help="Project id to repair.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    with SessionLocal() as db:
        project = (
            db.query(Project)
            .filter(
                Project.id == args.project_id,
                Project.workspace_id == args.workspace_id,
                Project.deleted_at.is_(None),
            )
            .first()
        )
        if project is None:
            print(
                json.dumps(
                    {
                        "error": "project_not_found",
                        "workspace_id": args.workspace_id,
                        "project_id": args.project_id,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                file=sys.stderr,
            )
            return 1

        summary = repair_project_memory_graph(
            db,
            workspace_id=args.workspace_id,
            project_id=args.project_id,
        )
        db.commit()

        print(
            json.dumps(
                {
                    "workspace_id": args.workspace_id,
                    "project_id": args.project_id,
                    "project_name": project.name,
                    "summary": summary.as_dict(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
