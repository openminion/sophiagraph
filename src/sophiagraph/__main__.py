"""Standalone smoke entrypoint for the reusable ``sophiagraph`` package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from sophiagraph.models import MemoryRecord
from sophiagraph.storage import create_sqlite_store, default_db_path


def _seed_record() -> MemoryRecord:
    return MemoryRecord(
        id=str(uuid4()),
        scope="agent:standalone",
        type="fact",
        key="standalone-smoke",
        title="Standalone smoke",
        content={"message": "sophiagraph standalone runtime OK"},
        created_at="2026-05-22T00:00:00+00:00",
        updated_at="2026-05-22T00:00:00+00:00",
        source="validated",
        confidence=1.0,
        event_time="2026-05-22T00:00:00+00:00",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="sophiagraph standalone smoke")
    parser.add_argument("--root", default=str(Path.cwd() / ".sophiagraph-runtime"))
    parser.add_argument("--seed", action="store_true", help="insert a sample record")
    parser.add_argument("--json", action="store_true", help="emit JSON summary")
    args = parser.parse_args(argv)

    store = create_sqlite_store(args.root)
    if args.seed and store.record_count() == 0:
        store.put_record(_seed_record())

    summary = {
        "db_path": str(default_db_path(args.root)),
        "record_count": store.record_count(),
        "candidate_count": store.candidate_count(),
    }
    if args.json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print(f"sophiagraph standalone runtime OK: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
