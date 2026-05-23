"""Minimal standalone `sophiagraph` quickstart example."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from uuid import uuid4

from sophiagraph.models import MemoryNamespace, MemoryRecord
from sophiagraph.portability.models import (
    MemoryBundleExportOptions,
    MemoryBundleImportOptions,
)
from sophiagraph.query import ListQueryOptions, SearchQueryOptions
from sophiagraph.storage import create_memory_store, create_sqlite_store


def build_sample_record() -> MemoryRecord:
    namespace = MemoryNamespace(
        tenant_id="tenant-demo",
        user_id="user-demo",
        agent_id="quickstart",
        graph_id="main",
    )
    return MemoryRecord(
        id=str(uuid4()),
        scope="agent:quickstart",
        type="fact",
        key="project:apollo",
        title="Apollo launch date",
        content={"text": "Apollo launched in Q2"},
        created_at="2026-05-22T00:00:00+00:00",
        updated_at="2026-05-22T00:00:00+00:00",
        source="validated",
        confidence=0.95,
        event_time="2026-05-22T00:00:00+00:00",
        namespace=namespace,
    )


def run_quickstart(root: str | Path) -> dict[str, object]:
    store = create_sqlite_store(root)
    record = build_sample_record()
    store.put_record(record)

    namespace_filter = MemoryNamespace(agent_id="quickstart")
    listed = store.list_records(
        ListQueryOptions(
            scopes=["agent:quickstart"],
            namespaces=[namespace_filter],
        )
    )
    searched = store.search_records(
        SearchQueryOptions(
            query="Apollo",
            scopes=["agent:quickstart"],
            namespaces=[namespace_filter],
        )
    )

    snapshot = store.export_snapshot(
        MemoryBundleExportOptions(
            scopes=["agent:quickstart"],
            include_relations=True,
            namespaces=[namespace_filter],
        )
    )
    imported = create_memory_store()
    imported.import_snapshot(snapshot, MemoryBundleImportOptions())

    return {
        "record_id": record.id,
        "listed_count": len(listed),
        "searched_count": len(searched),
        "imported_count": len(
            imported.list_records(ListQueryOptions(scopes=["agent:quickstart"]))
        ),
    }


def main() -> int:
    summary = run_quickstart(Path(tempfile.mkdtemp(prefix="sophiagraph-quickstart-")))
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
