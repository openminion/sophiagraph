"""Shared external-vector lifecycle helpers for storage backends."""

from __future__ import annotations

import sqlite3

from sophiagraph.models import MemoryEmbedding
from sophiagraph.models.embedding_lifecycle import namespace_key


def mark_memory_external_vector_active(
    orphans: dict[tuple[str, str], str], embedding: MemoryEmbedding
) -> None:
    if embedding.external_vector_id:
        orphans.pop(
            (namespace_key(embedding.namespace), embedding.external_vector_id), None
        )


def mark_sqlite_external_vector_active(
    conn: sqlite3.Connection, embedding: MemoryEmbedding
) -> None:
    if not embedding.external_vector_id:
        return
    conn.execute(
        """
        DELETE FROM sophiagraph_orphan_external_vector_ids
         WHERE namespace_key = ? AND external_vector_id = ?
        """,
        (namespace_key(embedding.namespace), embedding.external_vector_id),
    )


__all__ = [
    "mark_memory_external_vector_active",
    "mark_sqlite_external_vector_active",
]
