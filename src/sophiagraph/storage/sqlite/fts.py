"""SQLite FTS helpers for records and blocks."""

from __future__ import annotations

import sqlite3

from sophiagraph.models import KnowledgeDocumentBlock, MemoryRecord
from sophiagraph.query import StructuralSearchQuery


def ensure_fts_schema(conn: sqlite3.Connection) -> None:
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS sophiagraph_record_fts
            USING fts5(record_id UNINDEXED, searchable)
            """
        )
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS sophiagraph_block_fts
            USING fts5(block_id UNINDEXED, record_id UNINDEXED, searchable)
            """
        )
    except sqlite3.OperationalError:
        return


def record_searchable_text(record: MemoryRecord) -> str:
    return " ".join(
        str(part)
        for part in (
            record.title,
            record.key,
            record.scope,
            record.type,
            record.tags,
            record.content,
            record.meta,
        )
        if part is not None
    )


def replace_record_fts(
    conn: sqlite3.Connection,
    record: MemoryRecord,
) -> None:
    try:
        conn.execute(
            "DELETE FROM sophiagraph_record_fts WHERE record_id = ?",
            (record.id,),
        )
        conn.execute(
            """
            INSERT INTO sophiagraph_record_fts(record_id, searchable)
            VALUES (?, ?)
            """,
            (record.id, record_searchable_text(record)),
        )
    except sqlite3.OperationalError:
        return


def block_searchable_text(block: KnowledgeDocumentBlock) -> str:
    return " ".join(
        str(part)
        for part in (
            block.block_id,
            block.document_id,
            block.record_id,
            block.block_type,
            block.anchor,
            block.excerpt,
        )
        if part is not None
    )


def replace_record_blocks_fts(
    conn: sqlite3.Connection,
    record_id: str,
    blocks: list[KnowledgeDocumentBlock],
) -> None:
    try:
        conn.execute(
            "DELETE FROM sophiagraph_block_fts WHERE record_id = ?",
            (record_id,),
        )
        conn.executemany(
            """
            INSERT INTO sophiagraph_block_fts(block_id, record_id, searchable)
            VALUES (?, ?, ?)
            """,
            [
                (block.block_id, block.record_id, block_searchable_text(block))
                for block in blocks
            ],
        )
    except sqlite3.OperationalError:
        return


def block_fts_candidate_record_ids(
    conn: sqlite3.Connection,
    query: StructuralSearchQuery,
) -> set[str] | None:
    terms = [query.block, query.section, query.task]
    escaped = [
        '"' + str(term).replace('"', '""') + '"'
        for term in terms
        if term is not None and str(term)
    ]
    if not escaped:
        return None
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT record_id FROM sophiagraph_block_fts
             WHERE sophiagraph_block_fts MATCH ?
            """,
            (" AND ".join(escaped),),
        ).fetchall()
    except sqlite3.OperationalError:
        return None
    return {str(row["record_id"]) for row in rows}


def fts_candidate_record_ids(
    conn: sqlite3.Connection,
    query: StructuralSearchQuery,
) -> set[str] | None:
    terms = list(query.text_terms)
    terms.extend(query.exact_phrases)
    if query.content:
        terms.append(query.content)
    if not terms:
        return None
    escaped = ['"' + str(term).replace('"', '""') + '"' for term in terms if str(term)]
    if not escaped:
        return None
    try:
        rows = conn.execute(
            """
            SELECT record_id FROM sophiagraph_record_fts
             WHERE sophiagraph_record_fts MATCH ?
            """,
            (" AND ".join(escaped),),
        ).fetchall()
    except sqlite3.OperationalError:
        return None
    return {str(row["record_id"]) for row in rows}


__all__ = [
    "block_fts_candidate_record_ids",
    "block_searchable_text",
    "fts_candidate_record_ids",
    "replace_record_blocks_fts",
    "replace_record_fts",
    "record_searchable_text",
]
