"""Inspect Sophiagraph storage capability reports and portability."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from sophiagraph import (
    MemoryBundleExportOptions,
    MemoryBundleImportOptions,
    MemoryNamespace,
    MemoryRecord,
    SophiaGraphMemoryStore,
    SophiaGraphSqliteStore,
    build_store_capability_report,
)


def _record(record_id: str) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope="agent:demo",
        type="fact",
        key=f"fact:{record_id}",
        title="Backend capability demo",
        content={"text": "storage capability reports are portable"},
        created_at="2026-07-02T00:00:00+00:00",
        updated_at="2026-07-02T00:00:00+00:00",
        event_time="2026-07-02T00:00:00+00:00",
        source="validated",
        namespace=MemoryNamespace(agent_id="demo", graph_id="main"),
    )


def main() -> None:
    memory_store = SophiaGraphMemoryStore()
    memory_store.put_record(_record("memory-demo"))

    with TemporaryDirectory(prefix="sophiagraph-storage-demo-") as temp_dir:
        sqlite_store = SophiaGraphSqliteStore(Path(temp_dir) / "sophiagraph.sqlite3")
        snapshot = memory_store.export_snapshot(
            MemoryBundleExportOptions(scopes=["agent:demo"])
        )
        sqlite_store.import_snapshot(snapshot, MemoryBundleImportOptions())

        memory_report = build_store_capability_report(memory_store)
        sqlite_report = build_store_capability_report(sqlite_store)
        print(
            json.dumps(
                {
                    "memory_backend": memory_report.backend,
                    "memory_record_count": memory_report.record_count,
                    "sqlite_backend": sqlite_report.backend,
                    "sqlite_durable": sqlite_report.durable,
                    "sqlite_fts_supported": sqlite_report.fts_supported,
                    "sqlite_record_count": sqlite_report.record_count,
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
