"""Reusable certification fixtures for public SophiaGraph APIs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sophiagraph import (
    LifecyclePolicy,
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    PromotionPredicate,
    PromotionPredicateKind,
)
from sophiagraph.models import (
    CategorySchema,
    EntityTypeSchema,
    OntologyDefinition,
    PropertySchema,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def days_ago_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def cert_namespace(
    *, agent_id: str = "cert", session_id: str = "cert-1"
) -> MemoryNamespace:
    """Default certification namespace for fixtures."""

    return MemoryNamespace(agent_id=agent_id, session_id=session_id)


@dataclass(frozen=True)
class SeedRecord:
    record_id: str
    content: str


def seed_records(
    store,
    *,
    namespace: MemoryNamespace | None = None,
    count: int = 3,
) -> list[SeedRecord]:
    """Insert typed records and return their IDs."""

    ns = namespace or cert_namespace()
    now = utc_now_iso()
    seeded: list[SeedRecord] = []
    for i in range(count):
        record = MemoryRecord(
            id=f"cert-rec-{i}",
            scope=f"session:{ns.session_id or 'cert-1'}",
            type="fact",
            content=f"cert fact #{i}",
            created_at=now,
            updated_at=now,
            namespace=ns,
        )
        store.put_record(record)
        seeded.append(SeedRecord(record_id=record.id, content=f"cert fact #{i}"))
    return seeded


def link_records(
    store,
    *,
    pairs: Iterable[tuple[str, str]],
    relation_type: str = "related_to",
) -> list[str]:
    """Link record pairs with a stable relation type."""

    now = utc_now_iso()
    relation_ids: list[str] = []
    for source, target in pairs:
        rel = MemoryRelation(
            relation_id=f"cert-rel-{source}-{target}",
            source_record_id=source,
            target_record_id=target,
            relation_type=relation_type,
            created_at=now,
        )
        relation_ids.append(store.put_relation(rel))
    return relation_ids


def register_default_ontology(
    store,
    *,
    namespace: MemoryNamespace | None = None,
) -> OntologyDefinition:
    """Register a minimal certification ontology."""

    ns = namespace or cert_namespace()
    ontology = OntologyDefinition(
        ontology_id="cert-ontology",
        version="1.0.0",
        owner="sophiagraph-cert",
        namespace=ns,
        compatibility="fresh",
        categories=[CategorySchema(name="Function")],
        entity_types=[
            EntityTypeSchema(
                name="Function",
                properties=[
                    PropertySchema(
                        name="language",
                        value_type="str",
                        required=True,
                    )
                ],
            )
        ],
    )
    store.put_ontology(ontology)
    return ontology


def register_default_lifecycle_policy(
    store,
    *,
    namespace: MemoryNamespace | None = None,
    policy_id: str = "cert-lifecycle",
) -> LifecyclePolicy:
    """Register a minimal cross-backend lifecycle policy."""

    ns = namespace or cert_namespace()
    policy = LifecyclePolicy(
        policy_id=policy_id,
        namespace_filter=ns,
        created_at_iso=utc_now_iso(),
        ttl_active_iso="P30D",
        ttl_cooling_iso="P7D",
        promotion_predicates=(
            PromotionPredicate(
                kind=PromotionPredicateKind.ACCESS_COUNT_ABOVE_THRESHOLD,
                threshold=3,
            ),
        ),
    )
    store.put_lifecycle_policy(policy)
    return policy


__all__ = [
    "SeedRecord",
    "cert_namespace",
    "days_ago_iso",
    "link_records",
    "register_default_lifecycle_policy",
    "register_default_ontology",
    "seed_records",
    "utc_now_iso",
]
