"""Capability reports for Sophiagraph storage and retrieval backends."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Any

from sophiagraph.contracts.types import MEMORY_CONTRACT_VERSION
from sophiagraph.query import CandidateListOptions, EmbeddingListOptions
from sophiagraph.storage.sqlite.schema import SCHEMA_VERSION as SQLITE_SCHEMA_VERSION

CAPABILITY_REPORT_VERSION = "sophiagraph.store_capability_report.v1alpha1"


@dataclass(frozen=True, slots=True)
class StoreCapabilityReport:
    """Serializable capability posture for one Sophiagraph store."""

    backend: str
    contract_version: str = MEMORY_CONTRACT_VERSION
    report_version: str = CAPABILITY_REPORT_VERSION
    durable: bool = False
    backup_supported: bool = False
    export_supported: bool = True
    import_supported: bool = True
    keyword_search_supported: bool = True
    fts_supported: bool = False
    graph_snapshot_supported: bool = True
    relation_query_supported: bool = True
    block_search_supported: bool = True
    memory_block_supported: bool = True
    namespace_governance_supported: bool = True
    deletion_state_supported: bool = True
    vector_lifecycle_supported: bool = True
    external_vector_ids_supported: bool = True
    active_model_sets_supported: bool = True
    optional_graph_backends: tuple[str, ...] = ("fake", "kuzu", "neo4j")
    optional_vector_backends: tuple[str, ...] = ("builtin", "qdrant")
    record_count: int = 0
    candidate_count: int = 0
    embedding_count: int = 0
    active_model_set_count: int = 0
    sqlite_schema_version: int | None = None
    diagnostics: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["optional_graph_backends"] = list(self.optional_graph_backends)
        payload["optional_vector_backends"] = list(self.optional_vector_backends)
        payload["diagnostics"] = list(self.diagnostics)
        return payload


def build_store_capability_report(store: Any) -> StoreCapabilityReport:
    """Return one typed capability report for ``store``."""

    backend = _backend_name(store)
    diagnostics = []
    sqlite_schema_version = None
    fts_supported = False
    if backend == "sqlite":
        sqlite_schema_version = _sqlite_user_version(store)
        fts_supported = _sqlite_fts_tables_available(store, sqlite_schema_version)
        if not fts_supported:
            diagnostics.append("sqlite_fts_unavailable")
    else:
        diagnostics.append("in_memory_store_uses_deterministic_python_search")
    return StoreCapabilityReport(
        backend=backend,
        durable=backend == "sqlite",
        backup_supported=hasattr(store, "backup"),
        fts_supported=fts_supported,
        record_count=_record_count(store),
        candidate_count=_candidate_count(store),
        embedding_count=_embedding_count(store),
        active_model_set_count=_active_model_set_count(store),
        sqlite_schema_version=sqlite_schema_version,
        diagnostics=tuple(diagnostics),
    )


def _backend_name(store: Any) -> str:
    name = type(store).__name__
    if name == "SophiaGraphSqliteStore":
        return "sqlite"
    if name == "SophiaGraphMemoryStore":
        return "memory"
    return name


def _record_count(store: Any) -> int:
    if hasattr(store, "record_count"):
        return int(store.record_count())
    return 0


def _candidate_count(store: Any) -> int:
    return len(store.list_candidates(CandidateListOptions()))


def _embedding_count(store: Any) -> int:
    return len(store.list_embeddings(EmbeddingListOptions(include_vectors=False)))


def _active_model_set_count(store: Any) -> int:
    return len(store.list_active_model_sets())


def _sqlite_user_version(store: Any) -> int:
    with store._connect() as conn:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _sqlite_fts_tables_available(store: Any, sqlite_schema_version: int) -> bool:
    with store._connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*)
              FROM sqlite_master
             WHERE type = 'table'
               AND name IN ('sophiagraph_record_fts', 'sophiagraph_block_fts')
            """
        ).fetchone()
        if int(row[0]) != 2:
            return False
        for table_name, column_name in (
            ("sophiagraph_record_fts", "record_id"),
            ("sophiagraph_block_fts", "block_id"),
        ):
            try:
                conn.execute(
                    f"SELECT {column_name} FROM {table_name} LIMIT 1"
                ).fetchall()
            except sqlite3.OperationalError:
                return False
    return SQLITE_SCHEMA_VERSION == sqlite_schema_version


__all__ = [
    "CAPABILITY_REPORT_VERSION",
    "StoreCapabilityReport",
    "build_store_capability_report",
]
