"""Shared private helpers for storage operation owners."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import BackupDescriptor
from sophiagraph.portability.codec import json_dumps


def _write_backup_descriptor(target_dir: Path, descriptor: BackupDescriptor) -> None:
    (target_dir / "backup_manifest.json").write_text(
        json_dumps(descriptor.to_dict(), indent=2),
        encoding="utf-8",
    )


def _read_backup_descriptor(source_dir: Path) -> BackupDescriptor:
    manifest_path = source_dir / "backup_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise InvalidArgumentError("backup manifest must decode to an object")
    return BackupDescriptor.from_dict(payload)


def _prepare_directory(target_path: str | Path) -> Path:
    target_dir = Path(target_path).expanduser().resolve(strict=False)
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _sqlite_wal_frame_position(db_path: Path) -> int:
    wal_path = db_path.with_name(f"{db_path.name}-wal")
    if not wal_path.exists():
        return 0
    with sqlite3.connect(db_path) as conn:
        page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
    if page_size <= 0:
        return 0
    wal_size = wal_path.stat().st_size
    return max(0, wal_size // page_size)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(value: datetime) -> str:
    return value.isoformat()


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)
