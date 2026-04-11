#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_APP = ROOT / "apps" / "api"
if str(API_APP) not in sys.path:
    sys.path.insert(0, str(API_APP))

from app.services.qwen_official_catalog import generate_snapshot, write_snapshot  # noqa: E402


def main() -> int:
    snapshot = generate_snapshot()
    output_path = write_snapshot(snapshot)
    print(f"Wrote {len(snapshot['items'])} models to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

