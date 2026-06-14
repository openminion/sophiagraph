"""Standalone certification coverage for public SophiaGraph APIs."""

from __future__ import annotations

from pathlib import Path

import pytest

from sophiagraph import (
    FreshnessLedgerEntry,
    SophiaGraphMemoryStore,
    SophiaGraphSqliteStore,
    VaultFilePayload,
    VaultImportOptions,
    apply_decision_to_record_meta,
    decide_replay,
    evaluate_policy,
    import_vault_files,
    plan_human_vault_import,
)
from sophiagraph.audit import (
    PolicyDecision,
    PolicyRequest,
    QualityEvalSignal,
    RetrievalEvent,
    WriteAcceptedEvent,
    WriteAttemptEvent,
    build_policy_denial_event,
    evaluate_policy_hooks,
)
from sophiagraph.contracts.errors import (
    InvalidArgumentError,
    OntologyValidationError,
)
from sophiagraph.models import MemoryNamespace, MemoryRecord
from sophiagraph.query import (
    ContextRequest,
    LocalGraphMode,
    ListQueryOptions,
)
from sophiagraph.storage.ontology_validator import validate_record_for_ontology

from .certification_fixtures import (
    cert_namespace,
    days_ago_iso,
    link_records,
    register_default_lifecycle_policy,
    register_default_ontology,
    seed_records,
    utc_now_iso,
)


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "cert.sqlite3")


def test_cert_seed_records_round_trip(store) -> None:
    seeded = seed_records(store, count=3)
    assert len(seeded) == 3
    for s in seeded:
        record = store.get_record(s.record_id)
        assert record is not None
        assert record.content == s.content


def test_cert_link_records_round_trip(store) -> None:
    seed_records(store, count=2)
    rel_ids = link_records(store, pairs=[("cert-rec-0", "cert-rec-1")])
    assert len(rel_ids) == 1
    out = store.list_relations("cert-rec-0", direction="out")
    assert len(out) == 1
    assert out[0].target_record_id == "cert-rec-1"


def test_cert_ontology_round_trip(store) -> None:
    ontology = register_default_ontology(store)
    fetched = store.get_ontology(ontology_id="cert-ontology", version="1.0.0")
    assert fetched is not None
    assert fetched.ontology_id == ontology.ontology_id


def test_cert_lifecycle_policy_round_trip(store) -> None:
    policy = register_default_lifecycle_policy(store)
    fetched = store.get_lifecycle_policy(policy.policy_id)
    assert fetched is not None
    assert fetched.policy_id == policy.policy_id


def test_cert_context_request_constructs_with_local_graph_mode() -> None:
    request = ContextRequest(
        scopes=["session:cert-1"],
        mode="local_graph",
        namespaces=[cert_namespace()],
        local_graph=LocalGraphMode(seed_record_ids=["cert-rec-0"], depth=2),
    )
    assert request.mode == "local_graph"
    assert request.local_graph is not None
    assert request.local_graph.depth == 2


def test_cert_namespace_isolation_filters_records(store) -> None:
    ns_a = MemoryNamespace(agent_id="alpha", session_id="s")
    ns_b = MemoryNamespace(agent_id="beta", session_id="s")
    now = utc_now_iso()
    store.put_record(
        MemoryRecord(
            id="alpha-rec",
            scope="session:s",
            type="fact",
            content="alpha-only",
            created_at=now,
            updated_at=now,
            namespace=ns_a,
        )
    )
    store.put_record(
        MemoryRecord(
            id="beta-rec",
            scope="session:s",
            type="fact",
            content="beta-only",
            created_at=now,
            updated_at=now,
            namespace=ns_b,
        )
    )
    # cross-namespace lookup must NOT return beta-rec
    from sophiagraph.query import ListQueryOptions

    rows_a = store.list_records(
        ListQueryOptions(scopes=["session:s"], namespaces=[ns_a])
    )
    ids_a = {r.id for r in rows_a}
    assert "alpha-rec" in ids_a
    assert "beta-rec" not in ids_a


def test_cert_invalid_temporal_fact_rejected_via_ontology(store) -> None:
    register_default_ontology(store)
    now = utc_now_iso()
    record = MemoryRecord(
        id="bad-rec",
        scope="session:cert-1",
        type="fact",
        content="bad",
        created_at=now,
        updated_at=now,
        namespace=cert_namespace(),
        # Missing required `language` property under the cert ontology.
        meta={
            "ontology_category": "Function",
            "ontology_entity_type": "Function",
            "properties": {},
        },
    )
    store.put_record(record)
    with pytest.raises(OntologyValidationError):
        validate_record_for_ontology(
            store, record, ontology_id="cert-ontology", version="1.0.0"
        )


def test_cert_duplicate_replay_is_idempotent_on_lifecycle_decision(store) -> None:
    """Re-application of the same lifecycle decision is a no-op."""

    seed_records(store, count=1)
    policy = register_default_lifecycle_policy(store)
    record = store.get_record("cert-rec-0")
    assert record is not None
    from dataclasses import replace

    aged = replace(record, updated_at=days_ago_iso(40))
    decision = evaluate_policy(aged, policy, utc_now_iso())
    once = apply_decision_to_record_meta(aged.meta, decision)
    twice = apply_decision_to_record_meta(once, decision)
    assert once == twice


def test_cert_freshness_replay_is_typed_and_idempotent(store) -> None:
    entry = FreshnessLedgerEntry.create(
        namespace=cert_namespace(),
        source_kind="connector",
        source_id="connector:cert",
        status="fresh",
        cursor="cur-1",
        content_hash="hash-1",
        updated_at=utc_now_iso(),
        record_ids=["cert-rec-0"],
    )
    store.put_freshness_entry(entry)
    store.put_freshness_entry(entry)

    same = decide_replay(entry, incoming_cursor="cur-1", incoming_hash="hash-1")
    changed = decide_replay(entry, incoming_cursor="cur-2", incoming_hash="hash-2")

    assert same.decision == "skip_unchanged"
    assert changed.decision == "ingest_changed"
    assert store.list_freshness_entries(
        source_kind="connector", source_id="connector:cert"
    ) == [entry]


def test_cert_unsupported_retrieval_mode_raises() -> None:
    with pytest.raises(InvalidArgumentError):
        ContextRequest(
            scopes=["session:cert-1"],
            mode="not_a_mode",  # type: ignore[arg-type]
            local_graph=LocalGraphMode(seed_record_ids=["cert-rec-0"]),
        )


def test_cert_governance_events_only_accept_structural_inputs() -> None:
    ns = cert_namespace()
    # WriteAttemptEvent: typed namespace required; no prose allowed.
    with pytest.raises(InvalidArgumentError):
        WriteAttemptEvent(
            namespace={"agent_id": "x"},  # type: ignore[arg-type]
            payload_kind="document",
            source_owner="x",
            target_kind="record",
        )
    # RetrievalEvent: selected_ids must be a tuple of stored IDs.
    with pytest.raises(InvalidArgumentError):
        RetrievalEvent(
            namespace=ns,
            source_owner="x",
            selected_ids=["rec-1"],  # type: ignore[arg-type]
        )
    # QualityEvalSignal: signal_kind must be a closed enum.
    with pytest.raises(InvalidArgumentError):
        QualityEvalSignal(
            namespace=ns,
            record_id="rec-1",
            signal_kind="vibe_check",  # type: ignore[arg-type]
            source_owner="x",
        )


def test_cert_policy_denial_flow_blocks_with_typed_event() -> None:
    ns = cert_namespace()

    def hook(req: PolicyRequest) -> PolicyDecision:
        return PolicyDecision(
            action="deny",
            policy_id="cert-deny",
            reason_code="POLICY_DENIED_BY_HOOK",
        )

    decision = evaluate_policy_hooks(
        PolicyRequest(
            namespace=ns,
            surface="write",
            source_owner="cert",
            target_kind="record",
            target_id="rec-X",
        ),
        [hook],
    )
    assert decision.denied
    request = PolicyRequest(
        namespace=ns,
        surface="write",
        source_owner="cert",
        target_kind="record",
        target_id="rec-X",
    )
    evt = build_policy_denial_event(request, decision)
    audit = evt.to_memory_audit_event()
    assert audit.details["reason_code"] == "POLICY_DENIED_BY_HOOK"


def test_cert_write_accepted_event_shape() -> None:
    evt = WriteAcceptedEvent(
        namespace=cert_namespace(),
        payload_kind="document",
        source_owner="cert",
        target_kind="record",
        target_id="cert-rec-0",
    )
    audit = evt.to_memory_audit_event()
    assert audit.event_type == "memory.write_accepted"
    assert audit.target_id == "cert-rec-0"


def test_cert_human_import_dry_run_is_explicit_and_non_destructive(store) -> None:
    options = VaultImportOptions(
        vault_id="vault-cert",
        namespace=cert_namespace(),
        scope="agent:notes",
        imported_at=utc_now_iso(),
    )
    import_vault_files(
        store,
        [VaultFilePayload(path="notes/alpha.md", content="# Alpha\n\nAlpha body\n")],
        options,
    )

    plan = plan_human_vault_import(
        store,
        [VaultFilePayload(path="notes/alpha.md", content="# Alpha\n\nChanged\n")],
        options,
    )

    assert plan.updated_count == 1
    assert plan.created_count == 0
    listed = store.list_records(
        ListQueryOptions(scopes=["agent:notes"], namespaces=[cert_namespace()])
    )
    assert len(listed) == 1
    assert listed[0].content["text"] == "# Alpha\n\nAlpha body\n"
