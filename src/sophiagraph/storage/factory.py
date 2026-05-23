"""Factory helpers for the standalone ``sophiagraph`` storage engine."""

from __future__ import annotations

from pathlib import Path

from sophiagraph.storage.constants import DEFAULT_DB_FILENAME
from sophiagraph.storage.memory import SophiaGraphMemoryStore
from sophiagraph.storage.sqlite import SophiaGraphSqliteStore


def default_db_path(root: str | Path) -> Path:
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    return root_path / DEFAULT_DB_FILENAME


def create_sqlite_store(root: str | Path) -> SophiaGraphSqliteStore:
    return SophiaGraphSqliteStore(default_db_path(root))


def create_memory_store() -> SophiaGraphMemoryStore:
    return SophiaGraphMemoryStore()
