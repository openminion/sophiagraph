from __future__ import annotations

import asyncio

from sophiagraph.models import (
    ExplicitLinkResolver,
    LinkResolutionCandidate,
    MemoryNamespace,
    MemoryRecord,
    StructuralLink,
)
from sophiagraph.schema import describe_schema
from sophiagraph.storage import SophiaGraphMemoryStore, async_store


def _namespace() -> MemoryNamespace:
    return MemoryNamespace(agent_id="agent", graph_id="main")


def _record(record_id: str, *, score: object = 1) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope="agent:agent",
        type="artifact_digest",
        title=record_id,
        content={"text": record_id},
        created_at="2026-05-24T00:00:00+00:00",
        updated_at="2026-05-24T00:00:00+00:00",
        namespace=_namespace(),
        meta={"properties": {"status": "active", "score": score}},
    )


def test_schema_describes_labels_properties_namespaces_and_conflicts() -> None:
    schema = describe_schema(
        records=[_record("one", score=1), _record("two", score="high")]
    )

    assert schema.node_labels == ["artifact_digest"]
    assert schema.property_keys["status"] == ["str"]
    assert {"property_key": "score", "types": ["int", "str"]} in schema.conflicts
    assert schema.namespace_dimensions == ["agent_id", "graph_id"]


def test_resolver_diagnostics_and_repair_are_explicit() -> None:
    namespace = _namespace()
    resolver = ExplicitLinkResolver(
        [
            LinkResolutionCandidate(
                "rec-target", "Target.md", "Target", namespace=namespace
            )
        ]
    )
    link = StructuralLink(
        link_id="link-1",
        source_record_id="rec-source",
        raw_target="target",
        link_kind="wikilink",
        resolution_status="unresolved",
        namespace=namespace,
    )

    diagnostic = resolver.diagnose("target", namespace=namespace)
    repaired = resolver.repair_targets([link], namespace=namespace)[0]

    assert diagnostic.status == "resolved"
    assert diagnostic.candidate_record_ids == ["rec-target"]
    assert repaired.resolution_status == "resolved"
    assert repaired.target_record_id == "rec-target"


def test_async_facade_wraps_sync_store_without_extra_dependencies() -> None:
    store = SophiaGraphMemoryStore()
    facade = async_store(store)
    record = _record("async-rec")

    async def scenario() -> None:
        assert await facade.put_record(record) == "async-rec"
        assert (await facade.get_record("async-rec")).id == "async-rec"
        assert (await facade.list_changes())[0].object_id == "async-rec"

    asyncio.run(scenario())
